// FortiProxy local client.
//
// Runs on the user's machine and exposes two ordinary local proxies:
//
//	HTTP / HTTPS (CONNECT)  on 127.0.0.1:8080   ← the Windows system proxy
//	SOCKS5                  on 127.0.0.1:1080
//
// Every connection that arrives on those ports is forwarded to the hosted
// proxy at proxy.zdstudios.network over a single WebSocket that carries a
// yamux-multiplexed session (see API.md for the protocol). Several sessions
// run at once so one stalled link never freezes the others.
package main

import (
	"bufio"
	"context"
	"crypto/rand"
	"encoding/base64"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/coder/websocket"
	"github.com/hashicorp/yamux"
)

// ── Configuration ───────────────────────────────────────────────────────────

const (
	serverURL   = "wss://proxy.zdstudios.network/tunnel"
	httpAddr    = "127.0.0.1:8080"
	socksAddr   = "127.0.0.1:1080"
	numSessions = 4 // the official app uses 4 links

	netTCP = 1
	netUDP = 2
)

// tokenObf is injected at build time from secrets.env by build.ps1 as
// base64( XOR(token, obfKey) ). It is never the plain token, so the real
// value stays out of source control and out of a `strings` scan of the exe.
// At runtime PROXY_TOKEN in the environment overrides it (handy for testing).
var tokenObf = ""

var obfKey = []byte{0x5A, 0x3C, 0x71, 0x2E, 0x88, 0x19, 0x4D, 0xA7}

func resolveToken() string {
	if t := strings.TrimSpace(os.Getenv("PROXY_TOKEN")); t != "" {
		return t
	}
	if tokenObf == "" {
		return ""
	}
	raw, err := base64.StdEncoding.DecodeString(tokenObf)
	if err != nil {
		return ""
	}
	out := make([]byte, len(raw))
	for i, b := range raw {
		out[i] = b ^ obfKey[i%len(obfKey)]
	}
	return string(out)
}

// ── Device identity ─────────────────────────────────────────────────────────

// deviceID stays the same between runs so kicks and bans stick to this machine.
func deviceID() string {
	dir, err := os.UserConfigDir()
	if err == nil {
		path := filepath.Join(dir, "FortiProxy", "device.id")
		if b, err := os.ReadFile(path); err == nil {
			if id := strings.TrimSpace(string(b)); id != "" {
				return id
			}
		}
		id := randomID()
		_ = os.MkdirAll(filepath.Dir(path), 0o755)
		_ = os.WriteFile(path, []byte(id), 0o644)
		return id
	}
	return randomID()
}

func randomID() string {
	var b [16]byte
	if _, err := io.ReadFull(rand.Reader, b[:]); err != nil {
		return "fp-" + strconv.FormatInt(time.Now().UnixNano(), 36)
	}
	return fmt.Sprintf("fp-%x", b)
}

func deviceName() string {
	if h, err := os.Hostname(); err == nil && h != "" {
		if len(h) > 64 {
			h = h[:64]
		}
		return h
	}
	return "Unknown"
}

func deviceOS() string {
	switch runtime.GOOS {
	case "windows":
		return "Windows"
	case "darwin":
		return "macOS"
	default:
		if runtime.GOOS == "" {
			return "Unknown"
		}
		return strings.ToUpper(runtime.GOOS[:1]) + runtime.GOOS[1:]
	}
}

// ── Status output (parsed by the desktop app) ────────────────────────────────

func status(line string) { fmt.Printf("FP_STATUS:%s\n", line) }
func logln(line string)  { fmt.Printf("[FortiProxy] %s\n", line) }

// fatal refusals (wrong token / kicked / disabled / banned): stop, don't retry.
func refuse(code int, reason string) {
	if reason == "" {
		reason = "connection refused by server"
	}
	fmt.Printf("FP_REFUSAL:%d:%s\n", code, reason)
	os.Exit(3)
}

// ── Session pool ──────────────────────────────────────────────────────────────

type pool struct {
	token string

	mu       sync.RWMutex
	sessions []*yamux.Session // one slot per link; nil while reconnecting

	rr     uint64 // round-robin cursor
	online int32  // number of live sessions (atomic)
}

func newPool(token string) *pool {
	return &pool{token: token, sessions: make([]*yamux.Session, numSessions)}
}

// run keeps every slot connected for the life of the program.
func (p *pool) run(ctx context.Context) {
	var wg sync.WaitGroup
	for i := 0; i < numSessions; i++ {
		wg.Add(1)
		go func(slot int) {
			defer wg.Done()
			p.keepSlotAlive(ctx, slot)
		}(i)
	}
	wg.Wait()
}

func (p *pool) keepSlotAlive(ctx context.Context, slot int) {
	backoff := 200 * time.Millisecond
	for ctx.Err() == nil {
		sess, err := p.dial(ctx)
		if err != nil {
			if slot == 0 {
				logln("connect failed: " + err.Error())
			}
			select {
			case <-ctx.Done():
				return
			case <-time.After(backoff):
			}
			backoff *= 2
			if backoff > 5*time.Second {
				backoff = 5 * time.Second
			}
			continue
		}

		backoff = 200 * time.Millisecond
		p.setSlot(slot, sess)
		if atomic.AddInt32(&p.online, 1) == 1 {
			status("online")
		}
		logln(fmt.Sprintf("link %d connected", slot+1))

		<-sess.CloseChan() // blocks until the link drops

		p.setSlot(slot, nil)
		if atomic.AddInt32(&p.online, -1) == 0 {
			status("offline")
		}
		logln(fmt.Sprintf("link %d dropped — reconnecting", slot+1))
	}
}

// dial opens one WebSocket, upgrades it to a yamux client session, and returns
// it. A 401/403 is fatal and ends the whole program.
func (p *pool) dial(ctx context.Context) (*yamux.Session, error) {
	hdr := http.Header{}
	hdr.Set("Authorization", "Bearer "+p.token)
	hdr.Set("X-Device-Id", deviceID())
	hdr.Set("X-Device-Name", deviceName())
	hdr.Set("X-Device-Os", deviceOS())

	dialCtx, cancel := context.WithTimeout(ctx, 20*time.Second)
	defer cancel()

	ws, resp, err := websocket.Dial(dialCtx, serverURL, &websocket.DialOptions{
		HTTPHeader:      hdr,
		CompressionMode: websocket.CompressionDisabled,
	})
	if err != nil {
		if resp != nil {
			switch resp.StatusCode {
			case 401:
				refuse(401, "wrong proxy token — this build can't connect")
			case 403:
				refuse(403, resp.Header.Get("X-Proxy-Refusal"))
			}
			return nil, fmt.Errorf("refused (%d)", resp.StatusCode)
		}
		return nil, err
	}
	ws.SetReadLimit(-1)

	conn := websocket.NetConn(context.Background(), ws, websocket.MessageBinary)
	cfg := yamux.DefaultConfig()
	cfg.MaxStreamWindowSize = 16 << 20 // the default 256 KiB caps throughput
	cfg.EnableKeepAlive = true
	cfg.KeepAliveInterval = 15 * time.Second
	cfg.LogOutput = io.Discard
	return yamux.Client(conn, cfg)
}

func (p *pool) setSlot(slot int, sess *yamux.Session) {
	p.mu.Lock()
	p.sessions[slot] = sess
	p.mu.Unlock()
}

// openStream asks the server to connect to host:port and returns a stream that
// is piped to the caller. It tries each live link before giving up.
func (p *pool) openStream(network byte, host string, port uint16) (net.Conn, error) {
	p.mu.RLock()
	live := make([]*yamux.Session, 0, len(p.sessions))
	for _, s := range p.sessions {
		if s != nil && !s.IsClosed() {
			live = append(live, s)
		}
	}
	p.mu.RUnlock()

	if len(live) == 0 {
		return nil, errors.New("no tunnel link available yet")
	}

	start := int(atomic.AddUint64(&p.rr, 1))
	var lastErr error
	for i := 0; i < len(live); i++ {
		sess := live[(start+i)%len(live)]
		conn, err := openOn(sess, network, host, port)
		if err == nil {
			return conn, nil
		}
		lastErr = err
	}
	return nil, lastErr
}

// openOn opens one yamux stream and performs the per-stream handshake:
// send [network][hostLen][host][port], then read one status byte.
func openOn(s *yamux.Session, network byte, host string, port uint16) (net.Conn, error) {
	if len(host) == 0 || len(host) > 255 {
		return nil, errors.New("bad host length")
	}
	st, err := s.OpenStream()
	if err != nil {
		return nil, err
	}

	header := make([]byte, 0, 2+len(host)+2)
	header = append(header, network, byte(len(host)))
	header = append(header, host...)
	header = binary.BigEndian.AppendUint16(header, port)

	_ = st.SetWriteDeadline(time.Now().Add(15 * time.Second))
	if _, err := st.Write(header); err != nil {
		st.Close()
		return nil, err
	}
	_ = st.SetReadDeadline(time.Now().Add(15 * time.Second))
	var statusByte [1]byte
	if _, err := io.ReadFull(st, statusByte[:]); err != nil {
		st.Close()
		return nil, err
	}
	if statusByte[0] != 0 {
		st.Close()
		return nil, fmt.Errorf("server couldn't reach %s:%d", host, port)
	}
	_ = st.SetDeadline(time.Time{}) // clear deadlines for the data phase
	return st, nil
}

// pipe copies bytes both ways and closes both ends when either side finishes.
func pipe(a, b net.Conn) {
	done := make(chan struct{}, 2)
	go func() { io.Copy(a, b); done <- struct{}{} }()
	go func() { io.Copy(b, a); done <- struct{}{} }()
	<-done
	a.Close()
	b.Close()
}

// ── Local HTTP / HTTPS (CONNECT) proxy ────────────────────────────────────────

func serveHTTP(p *pool, client net.Conn) {
	defer func() { _ = recover() }() // one bad connection must never crash the client
	defer client.Close()

	br := bufio.NewReader(client)
	firstLine, err := br.ReadString('\n')
	if err != nil {
		return
	}
	parts := strings.Fields(firstLine)
	if len(parts) < 2 {
		return
	}
	method, target := parts[0], parts[1]

	// Drain the rest of the request headers.
	var headerBuf strings.Builder
	headerBuf.WriteString(firstLine)
	for {
		line, err := br.ReadString('\n')
		if err != nil {
			return
		}
		headerBuf.WriteString(line)
		if line == "\r\n" || line == "\n" {
			break
		}
	}

	var host string
	var port uint16

	if strings.EqualFold(method, "CONNECT") {
		host, port = splitHostPort(target, 443)
		stream, err := p.openStream(netTCP, host, port)
		if err != nil {
			client.Write([]byte("HTTP/1.1 503 Service Unavailable\r\nProxy-agent: FortiProxy/3.0\r\nContent-Length: 0\r\n\r\n"))
			return
		}
		client.Write([]byte("HTTP/1.1 200 Connection Established\r\nProxy-agent: FortiProxy/3.0\r\n\r\n"))
		// Flush anything the reader already buffered past the headers.
		if n := br.Buffered(); n > 0 {
			buf := make([]byte, n)
			io.ReadFull(br, buf)
			stream.Write(buf)
		}
		pipe(stream, client)
		return
	}

	// Plain HTTP: absolute-form request line (GET http://host/path ...).
	u, err := url.Parse(target)
	if err != nil || u.Host == "" {
		client.Write([]byte("HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n"))
		return
	}
	defPort := uint16(80)
	if u.Scheme == "https" {
		defPort = 443
	}
	host, port = splitHostPort(u.Host, defPort)

	stream, err := p.openStream(netTCP, host, port)
	if err != nil {
		client.Write([]byte("HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\n\r\n"))
		return
	}
	// Replay the original request to the origin server, then pipe.
	stream.Write([]byte(headerBuf.String()))
	if n := br.Buffered(); n > 0 {
		buf := make([]byte, n)
		io.ReadFull(br, buf)
		stream.Write(buf)
	}
	pipe(stream, client)
}

// ── Local SOCKS5 proxy (TCP CONNECT only) ─────────────────────────────────────

func serveSOCKS(p *pool, client net.Conn) {
	defer func() { _ = recover() }() // one bad connection must never crash the client
	defer client.Close()
	br := bufio.NewReader(client)

	// Greeting: VER, NMETHODS, METHODS...
	head := make([]byte, 2)
	if _, err := io.ReadFull(br, head); err != nil || head[0] != 0x05 {
		return
	}
	methods := make([]byte, int(head[1]))
	if _, err := io.ReadFull(br, methods); err != nil {
		return
	}
	client.Write([]byte{0x05, 0x00}) // no authentication

	// Request: VER, CMD, RSV, ATYP, ADDR, PORT
	req := make([]byte, 4)
	if _, err := io.ReadFull(br, req); err != nil || req[0] != 0x05 {
		return
	}
	cmd, atyp := req[1], req[3]

	var host string
	switch atyp {
	case 0x01: // IPv4
		b := make([]byte, 4)
		if _, err := io.ReadFull(br, b); err != nil {
			return
		}
		host = net.IP(b).String()
	case 0x03: // domain
		l := make([]byte, 1)
		if _, err := io.ReadFull(br, l); err != nil {
			return
		}
		b := make([]byte, int(l[0]))
		if _, err := io.ReadFull(br, b); err != nil {
			return
		}
		host = string(b)
	case 0x04: // IPv6
		b := make([]byte, 16)
		if _, err := io.ReadFull(br, b); err != nil {
			return
		}
		host = net.IP(b).String()
	default:
		client.Write([]byte{0x05, 0x08, 0x00, 0x01, 0, 0, 0, 0, 0, 0})
		return
	}

	pb := make([]byte, 2)
	if _, err := io.ReadFull(br, pb); err != nil {
		return
	}
	port := binary.BigEndian.Uint16(pb)

	if cmd != 0x01 { // only CONNECT
		client.Write([]byte{0x05, 0x07, 0x00, 0x01, 0, 0, 0, 0, 0, 0})
		return
	}

	stream, err := p.openStream(netTCP, host, port)
	if err != nil {
		client.Write([]byte{0x05, 0x05, 0x00, 0x01, 0, 0, 0, 0, 0, 0}) // connection refused
		return
	}
	client.Write([]byte{0x05, 0x00, 0x00, 0x01, 0, 0, 0, 0, 0, 0}) // succeeded

	if n := br.Buffered(); n > 0 {
		buf := make([]byte, n)
		io.ReadFull(br, buf)
		stream.Write(buf)
	}
	pipe(stream, client)
}

func splitHostPort(target string, def uint16) (string, uint16) {
	h, pStr, err := net.SplitHostPort(target)
	if err != nil {
		return strings.Trim(target, "[]"), def
	}
	p, err := strconv.Atoi(pStr)
	if err != nil || p <= 0 || p > 65535 {
		return h, def
	}
	return h, uint16(p)
}

// ── Entry point ───────────────────────────────────────────────────────────────

func main() {
	// Guardian mode: a detached watchdog that heals a stale proxy if the main
	// client dies hard. Handled before anything else.
	if len(os.Args) > 1 && os.Args[1] == "--guard" {
		runGuardian(os.Args)
		return
	}

	// Safety net: clear the system proxy on signal or panic.
	installExitCleanup()
	defer clearProxyIfOurs()

	token := resolveToken()
	if token == "" {
		logln("no proxy token — rebuild with secrets.env or set PROXY_TOKEN")
		refuse(401, "no proxy token in this build")
	}

	p := newPool(token)

	// HTTP proxy is required; SOCKS5 is best-effort.
	httpLn, err := net.Listen("tcp", httpAddr)
	if err != nil {
		logln("HTTP proxy failed to start: " + err.Error())
		os.Exit(1)
	}
	logln("HTTP proxy  on " + httpAddr)
	logln("Device: " + deviceName())

	// Start the detached guardian now that the listener is up.
	spawnGuardian()
	status("listening")

	go func() {
		if sl, err := net.Listen("tcp", socksAddr); err == nil {
			logln("SOCKS5 proxy on " + socksAddr)
			for {
				c, err := sl.Accept()
				if err != nil {
					continue
				}
				go serveSOCKS(p, c)
			}
		} else {
			logln("SOCKS5 unavailable (" + err.Error() + ") — continuing without it")
		}
	}()

	go p.run(context.Background())

	for {
		c, err := httpLn.Accept()
		if err != nil {
			continue
		}
		go serveHTTP(p, c)
	}
}
