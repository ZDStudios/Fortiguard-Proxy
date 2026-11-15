// Package tunnel is the client half of the tunnel: a pool of authenticated
// sessions to the server that any number of proxied connections share.
package tunnel

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"fortiproxy/internal/proto"

	"github.com/coder/websocket"
	"github.com/hashicorp/yamux"
	"golang.org/x/time/rate"
)

// Several sessions rather than one: every session is a single TCP connection
// underneath, so one lost packet stalls everything sharing it.
const DefaultSessions = 4

var (
	ErrBadToken = errors.New("the server rejected this app's access token")
	ErrBlocked  = errors.New("the server turned this device away")
	ErrClosed   = errors.New("tunnel closed")
)

type Options struct {
	URL        string
	Token      string
	DeviceID   string
	DeviceName string
	DeviceOS   string
	Sessions   int
	// DialContext opens the socket to the server. The app uses it to keep the
	// tunnel's own traffic off the virtual adapter.
	DialContext func(ctx context.Context, network, addr string) (net.Conn, error)
	// OnFatal runs when the server refuses this device while reconnecting.
	OnFatal func(error)
	// Logf receives connection events. Level is "info", "warn" or "error".
	Logf func(level, format string, args ...any)
}

type Client struct {
	opts   Options
	http   *http.Client
	wsURL  string
	ctx    context.Context
	cancel context.CancelFunc

	mu    sync.Mutex
	slots []*yamux.Session
	ready chan struct{} // closed and replaced whenever a session comes up
	next  atomic.Uint64

	Up, Down atomic.Uint64

	downLimit, upLimit atomic.Pointer[rate.Limiter]
}

func (c *Client) logf(level, format string, args ...any) {
	if c.opts.Logf != nil {
		c.opts.Logf(level, format, args...)
	}
}

// SetLimits caps speed in bytes per second, taking effect immediately. Zero
// means no limit.
func (c *Client) SetLimits(down, up int64) {
	c.downLimit.Store(newLimiter(down))
	c.upLimit.Store(newLimiter(up))
}

func newLimiter(bps int64) *rate.Limiter {
	if bps <= 0 {
		return nil
	}
	burst := int(max(bps/8, 64<<10)) // about 125 ms of data, so limits feel smooth
	return rate.NewLimiter(rate.Limit(bps), burst)
}

func (c *Client) throttle(l *rate.Limiter, n int) {
	if l == nil {
		return
	}
	for n > 0 {
		chunk := min(n, l.Burst())
		if l.WaitN(c.ctx, chunk) != nil {
			return
		}
		n -= chunk
	}
}

// Ping measures the round trip to the server over a live link.
func (c *Client) Ping() (time.Duration, error) {
	ctx, cancel := context.WithTimeout(c.ctx, 3*time.Second)
	defer cancel()
	s, err := c.pick(ctx)
	if err != nil {
		return 0, err
	}
	return s.Ping()
}

func New(o Options) (*Client, error) {
	if o.Sessions <= 0 {
		o.Sessions = DefaultSessions
	}
	u, err := url.Parse(o.URL)
	if err != nil || u.Host == "" {
		return nil, fmt.Errorf("invalid server URL %q", o.URL)
	}
	switch u.Scheme {
	case "https", "wss":
		u.Scheme = "wss"
	case "http", "ws":
		u.Scheme = "ws"
	default:
		return nil, fmt.Errorf("invalid server URL %q", o.URL)
	}
	u.Path = strings.TrimRight(u.Path, "/") + proto.TunnelPath

	tr := &http.Transport{
		DialContext:         o.DialContext,
		TLSHandshakeTimeout: 10 * time.Second,
		DisableKeepAlives:   true,
	}
	ctx, cancel := context.WithCancel(context.Background())
	return &Client{
		opts:   o,
		http:   &http.Client{Transport: tr},
		wsURL:  u.String(),
		ctx:    ctx,
		cancel: cancel,
		slots:  make([]*yamux.Session, o.Sessions),
		ready:  make(chan struct{}),
	}, nil
}

// Connect brings up the first session and returns any error directly, so a bad
// token or a dead server is reported before the computer's routes change. The
// remaining sessions then come up in the background.
func (c *Client) Connect(ctx context.Context) error {
	s, err := c.dial(ctx)
	if err != nil {
		return err
	}
	c.set(0, s)
	go c.keep(0, s)
	for i := 1; i < len(c.slots); i++ {
		go c.keep(i, nil)
	}
	return nil
}

func (c *Client) dial(ctx context.Context) (*yamux.Session, error) {
	ctx, cancel := context.WithTimeout(ctx, 15*time.Second)
	defer cancel()
	h := http.Header{}
	h.Set("Authorization", "Bearer "+c.opts.Token)
	h.Set(proto.HeaderDeviceID, c.opts.DeviceID)
	h.Set(proto.HeaderDeviceName, c.opts.DeviceName)
	h.Set(proto.HeaderDeviceOS, c.opts.DeviceOS)
	ws, resp, err := websocket.Dial(ctx, c.wsURL, &websocket.DialOptions{
		HTTPClient:      c.http,
		HTTPHeader:      h,
		CompressionMode: websocket.CompressionDisabled,
	})
	if err != nil {
		if resp != nil {
			switch resp.StatusCode {
			case http.StatusUnauthorized:
				return nil, ErrBadToken
			case http.StatusForbidden:
				if msg := resp.Header.Get(proto.HeaderRefusal); msg != "" {
					return nil, fmt.Errorf("%w: %s", ErrBlocked, msg)
				}
				return nil, ErrBlocked
			}
		}
		return nil, err
	}
	ws.SetReadLimit(-1)
	conn := WrapWebSocket(c.ctx, ws)
	s, err := yamux.Client(conn, proto.YamuxConfig())
	if err != nil {
		conn.Close()
		return nil, err
	}
	return s, nil
}

func (c *Client) set(i int, s *yamux.Session) {
	c.mu.Lock()
	c.slots[i] = s
	if s != nil {
		close(c.ready)
		c.ready = make(chan struct{})
	}
	c.mu.Unlock()
}

// keep holds slot i open for the life of the client.
func (c *Client) keep(i int, s *yamux.Session) {
	wait := 200 * time.Millisecond
	fails := 0
	if s != nil {
		c.logf("info", "Link %d connected", i+1)
	}
	for {
		if s != nil {
			select {
			case <-s.CloseChan():
			case <-c.ctx.Done():
				s.Close()
				return
			}
			c.set(i, nil)
			s = nil
			wait = 200 * time.Millisecond
			fails = 0
			if c.ctx.Err() == nil {
				c.logf("warn", "Link %d dropped, reconnecting", i+1)
			}
		}
		next, err := c.dial(c.ctx)
		if c.ctx.Err() != nil {
			if next != nil {
				next.Close()
			}
			return
		}
		if errors.Is(err, ErrBadToken) || errors.Is(err, ErrBlocked) {
			if c.opts.OnFatal != nil {
				c.opts.OnFatal(err)
			}
			return
		}
		if err == nil {
			s = next
			c.set(i, s)
			c.logf("info", "Link %d connected", i+1)
			continue
		}
		if fails%6 == 0 {
			c.logf("error", "Link %d can't reach the server: %v", i+1, err)
		}
		fails++
		select {
		case <-time.After(wait):
		case <-c.ctx.Done():
			return
		}
		if wait *= 2; wait > 5*time.Second {
			wait = 5 * time.Second
		}
	}
}

// Connected reports how many sessions are currently up.
func (c *Client) Connected() int {
	c.mu.Lock()
	defer c.mu.Unlock()
	n := 0
	for _, s := range c.slots {
		if s != nil && !s.IsClosed() {
			n++
		}
	}
	return n
}

// Reset closes every session so they reconnect, used when the network changes.
func (c *Client) Reset() {
	c.mu.Lock()
	sessions := append([]*yamux.Session(nil), c.slots...)
	c.mu.Unlock()
	for _, s := range sessions {
		if s != nil {
			s.Close()
		}
	}
}

func (c *Client) Close() {
	c.cancel()
	c.Reset()
}

// pick returns a live session, waiting for one if the tunnel is reconnecting.
// Waiting rather than falling back to the direct route keeps traffic from
// leaving the tunnel during a dropout.
func (c *Client) pick(ctx context.Context) (*yamux.Session, error) {
	for {
		c.mu.Lock()
		start := c.next.Add(1)
		for i := range c.slots {
			s := c.slots[(int(start)+i)%len(c.slots)]
			if s != nil && !s.IsClosed() {
				c.mu.Unlock()
				return s, nil
			}
		}
		ready := c.ready
		c.mu.Unlock()
		select {
		case <-ready:
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-c.ctx.Done():
			return nil, ErrClosed
		}
	}
}

// Open connects to target through the server and returns once the destination
// has answered, so a refused connection reaches the app as refused.
func (c *Client) Open(ctx context.Context, t proto.Target) (net.Conn, error) {
	ctx, cancel := context.WithTimeout(ctx, 20*time.Second)
	defer cancel()
	var last error
	for attempt := 0; attempt < 3; attempt++ {
		s, err := c.pick(ctx)
		if err != nil {
			return nil, err
		}
		st, err := s.OpenStream()
		if err != nil {
			last = err
			continue
		}
		if dl, ok := ctx.Deadline(); ok {
			st.SetDeadline(dl)
		}
		if err := proto.WriteTarget(st, t); err != nil {
			st.Close()
			last = err
			continue
		}
		var status [1]byte
		if _, err := io.ReadFull(st, status[:]); err != nil {
			st.Close()
			last = err
			continue
		}
		st.SetDeadline(time.Time{})
		if status[0] != proto.StatusOK {
			st.Close()
			return nil, fmt.Errorf("server could not reach %s:%d", t.Host, t.Port)
		}
		return &counted{Stream: st, c: c}, nil
	}
	return nil, last
}

// counted tallies the bytes crossing the tunnel for the app's speed readout.
type counted struct {
	*yamux.Stream
	c *Client
}

func (s *counted) Read(p []byte) (int, error) {
	n, err := s.Stream.Read(p)
	s.c.Down.Add(uint64(n))
	s.c.throttle(s.c.downLimit.Load(), n)
	return n, err
}

func (s *counted) Write(p []byte) (int, error) {
	s.c.throttle(s.c.upLimit.Load(), len(p))
	n, err := s.Stream.Write(p)
	s.c.Up.Add(uint64(n))
	return n, err
}

// CloseWrite half-closes: closing a yamux stream sends FIN but keeps reading.
func (s *counted) CloseWrite() error { return s.Stream.Close() }

// WrapWebSocket turns a WebSocket into a net.Conn whose Close is immediate. The
// library's default Close waits on a closing handshake, which holds up
// reconnecting by seconds when the peer is the one that went away.
func WrapWebSocket(ctx context.Context, ws *websocket.Conn) net.Conn {
	return &wsConn{Conn: websocket.NetConn(ctx, ws, websocket.MessageBinary), ws: ws}
}

type wsConn struct {
	net.Conn
	ws *websocket.Conn
}

func (c *wsConn) Close() error { return c.ws.CloseNow() }

// Relay pumps bytes between two connections until both directions finish,
// passing half-closes through.
func Relay(a, b net.Conn) { RelaySized(a, b, 64<<10) }

// RelaySized is Relay with a chosen buffer size for each direction. A server
// carrying thousands of connections holds one pair per connection.
func RelaySized(a, b net.Conn, size int) {
	done := make(chan struct{}, 2)
	pipe := func(dst, src net.Conn) {
		buf := make([]byte, size)
		_, err := io.CopyBuffer(struct{ io.Writer }{dst}, struct{ io.Reader }{src}, buf)
		if cw, ok := dst.(interface{ CloseWrite() error }); ok && err == nil {
			cw.CloseWrite()
		} else {
			dst.Close()
			src.Close()
		}
		done <- struct{}{}
	}
	go pipe(a, b)
	go pipe(b, a)
	<-done
	// One side has finished. Give the other a while to finish, then tidy up.
	t := time.AfterFunc(2*time.Minute, func() { a.Close(); b.Close() })
	<-done
	t.Stop()
	a.Close()
	b.Close()
}
