package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/netip"
	"net/url"
	"os"
	"sort"
	"strings"
	"sync"
	"syscall"
	"time"

	"fortiproxy/internal/proto"
	"fortiproxy/internal/tunnel"

	tun "github.com/sagernet/sing-tun"
	"github.com/sagernet/sing/common/buf"
	"github.com/sagernet/sing/common/control"
	"github.com/sagernet/sing/common/logger"
	M "github.com/sagernet/sing/common/metadata"
	N "github.com/sagernet/sing/common/network"
)

const (
	adapterName = "FortiProxy"
	// A large MTU lets the local network stack move data in bigger pieces. The
	// packets never leave the machine at this size, because TCP ends here.
	tunMTU = 9000

	protoICMP   = 1
	protoUDP    = 17
	protoICMPv6 = 58

	// How long the tunnel may have no links before the fail-safe turns it off.
	failSafeAfter = 30 * time.Second
)

// Traffic that should keep going directly: your local network, your Tailscale
// network, multicast. The VPS can't reach these, so tunnelling them only breaks
// printers, casting, and file shares.
var (
	bypass4 = prefixes("10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16",
		"172.16.0.0/12", "192.168.0.0/16", "224.0.0.0/4")
	bypass6 = prefixes("fc00::/7", "fe80::/10", "ff00::/8")
)

func prefixes(list ...string) []netip.Prefix {
	out := make([]netip.Prefix, len(list))
	for i, s := range list {
		out[i] = netip.MustParsePrefix(s)
	}
	return out
}

type State string

const (
	StateOff        State = "off"
	StateConnecting State = "connecting"
	StateOn         State = "on"
	StateRetrying   State = "reconnecting"
	StateStopping   State = "stopping"
)

// Engine owns everything that exists while the proxy is on.
type Engine struct {
	Logs *Logs
	dir  string

	mu        sync.Mutex
	state     State
	stage     string
	lastErr   string
	settings  Settings
	active    Settings // the settings the running connection started with
	since     time.Time
	latency   time.Duration
	cancel    context.CancelFunc
	finished  chan struct{}
	stopFuncs []func()
	testing   bool
	lastTest  TestResult
	testSeq   int
	repairing bool

	client  *tunnel.Client
	finder  *control.DefaultInterfaceFinder
	monitor tun.DefaultInterfaceMonitor
	host    string

	ipMu sync.Mutex
	ips  []netip.Addr

	failMu   sync.Mutex
	lastFail map[string]time.Time
}

func NewEngine(dir string) *Engine {
	return &Engine{state: StateOff, dir: dir, Logs: &Logs{}, settings: loadSettings(dir), lastFail: map[string]time.Time{}}
}

type Status struct {
	State     string `json:"state"`
	Stage     string `json:"stage"`
	Error     string `json:"error"`
	Up        uint64 `json:"up"`
	Down      uint64 `json:"down"`
	Links     int    `json:"links"`
	LinksMax  int    `json:"linksMax"`
	LatencyMs int64  `json:"latencyMs"`
	Uptime    int64  `json:"uptime"`
	Server    string `json:"server"`
	Device    string `json:"device"`
	Stale     bool   `json:"stale"` // settings changed that need a reconnect
	Testing   bool   `json:"testing"`
	TestSeq   int    `json:"testSeq"` // goes up each time a test finishes
	Repairing bool   `json:"repairing"`

	Test TestResult `json:"test"`
}

func (e *Engine) Status() Status {
	e.mu.Lock()
	defer e.mu.Unlock()
	s := Status{State: string(e.state), Stage: e.stage, Error: e.lastErr, Device: deviceName(), Testing: e.testing,
		LinksMax: e.active.Links, TestSeq: e.testSeq, Test: e.lastTest, Repairing: e.repairing}
	if u, err := url.Parse(serverURL); err == nil {
		s.Server = u.Hostname()
	}
	if e.client != nil {
		s.Up, s.Down = e.client.Up.Load(), e.client.Down.Load()
		s.Links = e.client.Connected()
		if e.state == StateOn && s.Links == 0 {
			s.State = string(StateRetrying)
		}
		s.LatencyMs = e.latency.Milliseconds()
	}
	if e.state == StateOn {
		s.Uptime = int64(time.Since(e.since).Seconds())
		a, b := e.active, e.settings
		s.Stale = a.Links != b.Links || a.DNS != b.DNS || a.AllowQUIC != b.AllowQUIC || a.BlockIPv6 != b.BlockIPv6
	}
	return s
}

func (e *Engine) Settings() Settings {
	e.mu.Lock()
	defer e.mu.Unlock()
	return e.settings
}

// SetSettings saves new settings. Speed limits apply at once; the rest apply on
// the next connect, which Status reports through Stale.
func (e *Engine) SetSettings(s Settings) error {
	s = s.sanitize()
	if err := saveSettings(e.dir, s); err != nil {
		e.Logs.Add("error", "Couldn't save settings: %v", err)
		return err
	}
	e.mu.Lock()
	old := e.settings
	e.settings = s
	client := e.client
	e.mu.Unlock()
	if client != nil {
		client.SetLimits(mbps(s.DownMbps), mbps(s.UpMbps))
	}
	if old.DownMbps != s.DownMbps || old.UpMbps != s.UpMbps {
		e.Logs.Add("info", "Speed limit set: download %s, upload %s", limitText(s.DownMbps), limitText(s.UpMbps))
	}
	return nil
}

func mbps(n int) int64 { return int64(n) * 1_000_000 / 8 }

func limitText(n int) string {
	if n == 0 {
		return "unlimited"
	}
	return fmt.Sprintf("%d Mbps", n)
}

// Toggle starts the proxy if it is off and stops it otherwise.
func (e *Engine) Toggle() {
	e.mu.Lock()
	switch e.state {
	case StateOff:
		e.state = StateConnecting
		e.stage = "Starting"
		e.lastErr = ""
		e.active = e.settings
		e.latency = 0
		ctx, cancel := context.WithCancel(context.Background())
		e.cancel = cancel
		e.finished = make(chan struct{})
		e.mu.Unlock()
		go e.run(ctx)
	case StateConnecting, StateOn:
		e.mu.Unlock()
		go e.Stop("")
	default:
		e.mu.Unlock()
	}
}

// Reconnect restarts the connection so changed settings take effect.
func (e *Engine) Reconnect() {
	go func() {
		e.Logs.Add("info", "Reconnecting to apply settings")
		e.Stop("")
		e.Toggle()
	}()
}

// Stop turns the proxy off and waits until the computer's routes are restored.
func (e *Engine) Stop(reason string) {
	e.mu.Lock()
	if e.state == StateOff {
		e.mu.Unlock()
		return
	}
	if reason != "" {
		e.lastErr = reason
	}
	if e.state != StateStopping {
		e.Logs.Add("info", "Stopping")
	}
	e.state = StateStopping
	e.stage = "Restoring your network"
	cancel, finished := e.cancel, e.finished
	e.mu.Unlock()
	cancel()
	<-finished
}

func (e *Engine) setStage(text string) {
	e.mu.Lock()
	e.stage = text
	e.mu.Unlock()
	e.Logs.Add("info", "%s", text)
}

func (e *Engine) run(ctx context.Context) {
	started := time.Now()
	err := e.start(ctx)
	if err != nil {
		if errors.Is(err, context.Canceled) {
			e.Logs.Add("info", "Cancelled")
		} else {
			e.Logs.Add("error", "%s", friendly(err))
			e.mu.Lock()
			e.lastErr = friendly(err)
			e.mu.Unlock()
		}
	} else {
		e.mu.Lock()
		if e.state == StateConnecting {
			e.state = StateOn
			e.since = time.Now()
		}
		e.mu.Unlock()
		e.Logs.Add("info", "Connected in %.1fs. All traffic now goes through %s", time.Since(started).Seconds(), e.host)
		go e.measureLatency(ctx)
		go e.watchLinks(ctx)
		<-ctx.Done()
	}
	e.teardown()
	clearActive(e.dir)
	e.mu.Lock()
	e.state = StateOff
	e.stage = ""
	close(e.finished)
	e.mu.Unlock()
	e.Logs.Add("info", "Off. Your normal network is restored")
}

func (e *Engine) measureLatency(ctx context.Context) {
	for {
		if c := e.tunnelClient(); c != nil {
			if d, err := c.Ping(); err == nil {
				e.mu.Lock()
				e.latency = d
				e.mu.Unlock()
			}
		}
		select {
		case <-ctx.Done():
			return
		case <-time.After(3 * time.Second):
		}
	}
}

// watchLinks is the fail-safe. Holding traffic through a short dropout keeps it
// inside the tunnel, but holding it forever would look like broken internet, so
// after a while with no server the proxy turns itself off.
func (e *Engine) watchLinks(ctx context.Context) {
	var since time.Time
	warned := false
	for {
		select {
		case <-ctx.Done():
			return
		case <-time.After(time.Second):
		}
		c := e.tunnelClient()
		if c == nil {
			return
		}
		if c.Connected() > 0 {
			since, warned = time.Time{}, false
			continue
		}
		if since.IsZero() {
			since = time.Now()
		}
		if !warned {
			warned = true
			e.Logs.Add("warn", "Lost contact with the server. Holding traffic while it reconnects")
		}
		if time.Since(since) >= failSafeAfter && e.Settings().FailSafe {
			msg := fmt.Sprintf("Lost the server for %d seconds, so the proxy turned itself off to keep your internet working.", int(failSafeAfter.Seconds()))
			e.Logs.Add("error", "%s", msg)
			go e.Stop(msg)
			return
		}
	}
}

// Repair cleans up anything left behind by a crash. It runs in the background
// because it can take several seconds.
func (e *Engine) Repair() {
	e.mu.Lock()
	if e.state != StateOff || e.repairing {
		e.mu.Unlock()
		e.Logs.Add("warn", "Turn the proxy off before repairing the network")
		return
	}
	e.repairing = true
	e.mu.Unlock()
	e.Logs.Add("info", "Checking for anything left behind")
	go func() {
		e.Logs.Add("info", "%s", repairNetwork(e.dir))
		e.mu.Lock()
		e.repairing = false
		e.mu.Unlock()
	}()
}

// refusalText drops the wrapper, leaving what the server said.
func refusalText(err error) string {
	return strings.TrimPrefix(err.Error(), tunnel.ErrBlocked.Error()+": ")
}

func friendly(err error) string {
	switch {
	case errors.Is(err, tunnel.ErrBlocked):
		return refusalText(err)
	case errors.Is(err, tunnel.ErrBadToken):
		return err.Error()
	case errors.Is(err, context.DeadlineExceeded):
		return "The server took too long to answer."
	}
	return "Couldn't connect: " + err.Error()
}

func (e *Engine) teardown() {
	e.mu.Lock()
	fns := e.stopFuncs
	e.stopFuncs = nil
	e.mu.Unlock()
	for i := len(fns) - 1; i >= 0; i-- {
		fns[i]()
	}
	e.mu.Lock()
	e.client = nil
	e.mu.Unlock()
}

func (e *Engine) onStop(f func()) {
	e.mu.Lock()
	e.stopFuncs = append(e.stopFuncs, f)
	e.mu.Unlock()
}

func (e *Engine) start(ctx context.Context) error {
	if serverURL == "" || proxyToken == "" {
		return errors.New("this build has no server configured; rebuild with build.ps1")
	}
	u, err := url.Parse(serverURL)
	if err != nil {
		return err
	}
	e.host = u.Hostname()
	settings := e.Settings()

	e.setStage("Checking your network")
	e.finder = control.NewDefaultInterfaceFinder()
	if err := e.finder.Update(); err != nil {
		return err
	}
	log0 := logger.NOP()
	netMon, err := tun.NewNetworkUpdateMonitor(log0)
	if err != nil {
		return err
	}
	if err := netMon.Start(); err != nil {
		return err
	}
	e.onStop(func() { netMon.Close() })
	netMon.RegisterCallback(func() { e.finder.Update() })
	monitor, err := tun.NewDefaultInterfaceMonitor(netMon, log0, tun.DefaultInterfaceMonitorOptions{InterfaceFinder: e.finder})
	if err != nil {
		return err
	}
	if err := monitor.Start(); err != nil {
		if errors.Is(err, tun.ErrNoRoute) {
			return errors.New("this computer isn't connected to a network")
		}
		return err
	}
	e.onStop(func() { monitor.Close() })
	e.monitor = monitor
	if iface := monitor.DefaultInterface(); iface != nil {
		e.Logs.Add("info", "Using network adapter: %s", iface.Name)
	}

	// Look the server up now, while normal DNS still works.
	e.setStage("Finding " + e.host)
	lookup, cancel := context.WithTimeout(ctx, 8*time.Second)
	defer cancel()
	addrs, err := net.DefaultResolver.LookupNetIP(lookup, "ip", e.host)
	if err != nil {
		return fmt.Errorf("can't find the server: %w", err)
	}
	e.setIPs(addrs)

	client, err := tunnel.New(tunnel.Options{
		URL:         serverURL,
		Token:       proxyToken,
		DeviceID:    deviceID(),
		DeviceName:  deviceName(),
		DeviceOS:    deviceOS(),
		Sessions:    settings.Links,
		DialContext: e.dialServer,
		OnFatal: func(err error) {
			msg := friendly(err)
			e.Logs.Add("error", "%s", msg)
			go e.Stop(msg)
		},
		Logf: e.Logs.Add,
	})
	if err != nil {
		return err
	}
	client.SetLimits(mbps(settings.DownMbps), mbps(settings.UpMbps))
	e.mu.Lock()
	e.client = client
	e.mu.Unlock()
	e.onStop(client.Close)

	// Connect before touching routes. A bad token or a dead server then shows an
	// error and leaves the internet exactly as it was.
	e.setStage("Connecting to your server")
	if err := client.Connect(ctx); err != nil {
		return err
	}

	e.setStage("Creating the network adapter")
	if err := markActive(e.dir); err != nil {
		e.Logs.Add("warn", "Couldn't write the crash marker: %v", err)
	}
	opts := tun.Options{
		Name:                     adapterName,
		Inet4Address:             prefixes("172.19.0.1/30"),
		Inet6Address:             prefixes("fdfe:dcba:9876::1/126"),
		MTU:                      tunMTU,
		AutoRoute:                true,
		StrictRoute:              true, // stops DNS lookups escaping around the tunnel
		Inet4RouteExcludeAddress: append(append([]netip.Prefix{}, bypass4...), e.serverRoutes(true)...),
		Inet6RouteExcludeAddress: append(append([]netip.Prefix{}, bypass6...), e.serverRoutes(false)...),
		InterfaceFinder:          e.finder,
		InterfaceMonitor:         monitor,
		Logger:                   log0,
	}
	dev, err := tun.New(opts)
	if err != nil {
		return fmt.Errorf("creating the network adapter: %w", err)
	}
	e.onStop(func() { dev.Close() })

	stack, err := tun.NewStack("gvisor", tun.StackOptions{
		Context:         ctx,
		Tun:             dev,
		TunOptions:      opts,
		UDPTimeout:      time.Minute,
		UDPMapping:      tun.NATMappingAddressAndPortDependent,
		UDPFiltering:    tun.NATFilteringAddressAndPortDependent,
		Handler:         e,
		Logger:          log0,
		InterfaceFinder: e.finder,
	})
	if err != nil {
		return err
	}
	if err := stack.Start(); err != nil {
		return err
	}
	e.onStop(func() { stack.Close() })

	e.setStage("Routing traffic through the tunnel")
	if err := dev.Start(); err != nil {
		return fmt.Errorf("setting routes: %w", err)
	}

	monitor.RegisterCallback(func(*control.Interface, int) {
		e.Logs.Add("warn", "Network changed, reconnecting")
		client.Reset()
	})
	return nil
}

func (e *Engine) setIPs(addrs []netip.Addr) {
	// IPv4 first: it is the one that a hosting provider's firewall lets through.
	sort.SliceStable(addrs, func(i, j int) bool { return addrs[i].Unmap().Is4() && !addrs[j].Unmap().Is4() })
	e.ipMu.Lock()
	e.ips = addrs
	e.ipMu.Unlock()
}

func (e *Engine) serverRoutes(v4 bool) []netip.Prefix {
	e.ipMu.Lock()
	defer e.ipMu.Unlock()
	var out []netip.Prefix
	for _, a := range e.ips {
		a = a.Unmap()
		if a.Is4() == v4 {
			out = append(out, netip.PrefixFrom(a, a.BitLen()))
		}
	}
	return out
}

// bindPhysical pins a socket to the real network adapter, so the tunnel's own
// connection can never loop back into the tunnel.
func (e *Engine) bindPhysical() func(network, address string, c syscall.RawConn) error {
	return control.BindToInterfaceFunc(e.finder, func(network, address string) (string, int, error) {
		iface := e.monitor.DefaultInterface()
		if iface == nil {
			return "", -1, tun.ErrNoRoute
		}
		return iface.Name, iface.Index, nil
	})
}

// dialServer connects to the server by the addresses found at startup, and
// looks them up again over the real adapter if those stop working.
func (e *Engine) dialServer(ctx context.Context, network, addr string) (net.Conn, error) {
	_, port, err := net.SplitHostPort(addr)
	if err != nil {
		return nil, err
	}
	d := net.Dialer{Timeout: 8 * time.Second, Control: e.bindPhysical()}
	try := func(ips []netip.Addr) (net.Conn, error) {
		var last error = errors.New("no server addresses")
		for _, ip := range ips {
			c, err := d.DialContext(ctx, "tcp", net.JoinHostPort(ip.Unmap().String(), port))
			if err == nil {
				return c, nil
			}
			last = err
		}
		return nil, last
	}
	e.ipMu.Lock()
	ips := append([]netip.Addr(nil), e.ips...)
	e.ipMu.Unlock()
	conn, err := try(ips)
	if err == nil || ctx.Err() != nil {
		return conn, err
	}
	r := net.Resolver{PreferGo: true, Dial: func(ctx context.Context, network, _ string) (net.Conn, error) {
		return d.DialContext(ctx, "udp", net.JoinHostPort("1.1.1.1", "53"))
	}}
	fresh, lookupErr := r.LookupNetIP(ctx, "ip", e.host)
	if lookupErr != nil {
		return nil, err
	}
	e.setIPs(fresh)
	return try(fresh)
}

// JudgeFlow decides what happens to each new flow from the adapter.
func (e *Engine) JudgeFlow(network uint8, source, destination netip.AddrPort, firstPacket []byte) tun.FlowVerdict {
	e.mu.Lock()
	s := e.active
	e.mu.Unlock()
	ip := destination.Addr().Unmap()
	switch {
	case network == protoICMP || network == protoICMPv6:
		// The tunnel carries TCP and UDP only.
		return tun.FlowVerdict{Action: tun.ActionDrop}
	case destination.Port() == 53:
		return tun.FlowVerdict{Action: tun.ActionAccept}
	case network == protoUDP && destination.Port() == 443 && !s.AllowQUIC:
		// Refusing QUIC makes browsers use TCP at once. QUIC inside this TCP
		// tunnel would be slower, and it hides the site name from the dashboard.
		return tun.FlowVerdict{Action: tun.ActionReject}
	case ip.Is6() && s.BlockIPv6:
		// Answering "refused" makes apps fall back to IPv4 instantly, instead of
		// waiting on a server that may have no IPv6 at all.
		return tun.FlowVerdict{Action: tun.ActionReject}
	case !ip.IsGlobalUnicast():
		return tun.FlowVerdict{Action: tun.ActionDrop}
	}
	return tun.FlowVerdict{Action: tun.ActionAccept}
}

// NewDNSPacket is required by the interface. DNS arrives as ordinary UDP below.
func (e *Engine) NewDNSPacket([]byte, M.Socksaddr, M.Socksaddr, N.PacketWriter) {}

// target sends DNS to a public resolver: the address the system asked for is
// either this adapter's or a router on the LAN, and neither exists at the VPS.
func (e *Engine) target(network byte, dst M.Socksaddr) proto.Target {
	if dst.Port == 53 {
		e.mu.Lock()
		dns := e.active.DNS
		e.mu.Unlock()
		return proto.Target{Net: network, Host: dns, Port: 53}
	}
	return proto.Target{Net: network, Host: dst.AddrString(), Port: dst.Port}
}

func (e *Engine) tunnelClient() *tunnel.Client {
	e.mu.Lock()
	defer e.mu.Unlock()
	return e.client
}

// noteFailure logs a failed connection, at most once a minute per destination,
// because an app retrying in a loop would otherwise bury everything else.
func (e *Engine) noteFailure(t proto.Target, err error) {
	if errors.Is(err, tunnel.ErrClosed) || errors.Is(err, context.Canceled) {
		return
	}
	key := fmt.Sprintf("%s:%d", t.Host, t.Port)
	e.failMu.Lock()
	if len(e.lastFail) > 2000 {
		e.lastFail = map[string]time.Time{}
	}
	skip := time.Since(e.lastFail[key]) < time.Minute
	if !skip {
		e.lastFail[key] = time.Now()
	}
	e.failMu.Unlock()
	if !skip {
		e.Logs.Add("warn", "Couldn't connect to %s: %v", key, err)
	}
}

func closed(onClose N.CloseHandlerFunc, err error) {
	if onClose != nil {
		onClose(err)
	}
}

// NewConnectionEx carries one TCP connection. The app's connection only
// completes once the real destination has answered.
func (e *Engine) NewConnectionEx(ctx context.Context, conn net.Conn, source, destination M.Socksaddr, onClose N.CloseHandlerFunc) {
	c := e.tunnelClient()
	if c == nil {
		N.CloseOnHandshakeFailure(conn, onClose, tunnel.ErrClosed)
		return
	}
	t := e.target(proto.NetTCP, destination)
	up, err := c.Open(ctx, t)
	if err != nil {
		e.noteFailure(t, err)
		N.CloseOnHandshakeFailure(conn, onClose, err)
		return
	}
	if h, ok := conn.(N.HandshakeSuccess); ok {
		if err := h.HandshakeSuccess(); err != nil {
			up.Close()
			conn.Close()
			closed(onClose, err)
			return
		}
	}
	tunnel.Relay(conn, up)
	closed(onClose, nil)
}

// NewPacketConnectionEx carries one UDP flow.
func (e *Engine) NewPacketConnectionEx(ctx context.Context, conn N.PacketConn, source, destination M.Socksaddr, onClose N.CloseHandlerFunc) {
	go func() {
		defer conn.Close()
		c := e.tunnelClient()
		if c == nil {
			closed(onClose, tunnel.ErrClosed)
			return
		}
		t := e.target(proto.NetUDP, destination)
		up, err := c.Open(ctx, t)
		if err != nil {
			e.noteFailure(t, err)
			closed(onClose, err)
			return
		}
		defer up.Close()
		go func() {
			defer conn.Close()
			b := make([]byte, proto.MaxDatagram)
			for {
				n, err := proto.ReadDatagram(up, b)
				if err != nil {
					return
				}
				reply := buf.NewSize(n)
				reply.Write(b[:n])
				if conn.WritePacket(reply, destination) != nil {
					return
				}
				if destination.Port == 53 {
					return // a lookup gets one answer; free the flow straight away
				}
			}
		}()
		for {
			packet := buf.NewPacket()
			if _, err := conn.ReadPacket(packet); err != nil {
				packet.Release()
				break
			}
			err := proto.WriteDatagram(up, packet.Bytes())
			packet.Release()
			if err != nil {
				break
			}
		}
		closed(onClose, nil)
	}()
}

// TestResult is what the connection test found.
type TestResult struct {
	OK       bool    `json:"ok"`
	ExitIP   string  `json:"exitIp"`
	ServerIP string  `json:"serverIp"`
	Tunneled bool    `json:"tunneled"`
	DNSMs    int64   `json:"dnsMs"`
	FirstMs  int64   `json:"firstMs"`
	Mbps     float64 `json:"mbps"`
	Error    string  `json:"error"`
}

// StartTest runs the test in the background. The window's calls into Go happen
// on its UI thread, so anything slow would freeze it. Status carries the result.
func (e *Engine) StartTest() {
	go func() {
		r := e.Test()
		e.mu.Lock()
		e.lastTest = r
		e.testSeq++
		e.mu.Unlock()
	}()
}

// Test uses the computer's normal network path, exactly as any other app does.
// While the proxy is on that path is the tunnel, so the exit address it reports
// proves whether traffic is really leaving through the server.
func (e *Engine) Test() TestResult {
	e.mu.Lock()
	if e.testing {
		e.mu.Unlock()
		return TestResult{Error: "A test is already running."}
	}
	e.testing = true
	on := e.state == StateOn
	e.mu.Unlock()
	defer func() {
		e.mu.Lock()
		e.testing = false
		e.mu.Unlock()
	}()

	var r TestResult
	fail := func(step string, err error) TestResult {
		r.Error = step + ": " + err.Error()
		e.Logs.Add("error", "Connection test failed. %s", r.Error)
		return r
	}
	e.Logs.Add("info", "Connection test started")
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	start := time.Now()
	if _, err := net.DefaultResolver.LookupNetIP(ctx, "ip", "www.cloudflare.com"); err != nil {
		return fail("DNS lookup", err)
	}
	r.DNSMs = time.Since(start).Milliseconds()

	client := &http.Client{Transport: &http.Transport{DisableKeepAlives: true}}
	start = time.Now()
	body, err := fetch(ctx, client, "https://www.cloudflare.com/cdn-cgi/trace")
	if err != nil {
		return fail("Reaching the internet", err)
	}
	r.FirstMs = time.Since(start).Milliseconds()
	for _, line := range strings.Split(body, "\n") {
		if v, ok := strings.CutPrefix(line, "ip="); ok {
			r.ExitIP = v
		}
	}
	e.ipMu.Lock()
	for _, ip := range e.ips {
		if ip.Unmap().String() == r.ExitIP {
			r.Tunneled = true
		}
		if ip.Unmap().Is4() {
			r.ServerIP = ip.Unmap().String()
		}
	}
	e.ipMu.Unlock()
	r.Mbps = e.measureSpeed(ctx, client)
	r.OK = !on || r.Tunneled
	level := "info"
	if !r.OK {
		level = "error"
		r.Error = fmt.Sprintf("Traffic left through %s instead of your server %s.", r.ExitIP, r.ServerIP)
		e.Logs.Add(level, "%s", r.Error)
	}
	e.Logs.Add(level, "Connection test: exit IP %s, DNS %d ms, first response %d ms, download %.0f Mbps",
		r.ExitIP, r.DNSMs, r.FirstMs, r.Mbps)
	return r
}

func fetch(ctx context.Context, c *http.Client, url string) (string, error) {
	req, err := http.NewRequestWithContext(ctx, "GET", url, nil)
	if err != nil {
		return "", err
	}
	resp, err := c.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	b, err := io.ReadAll(io.LimitReader(resp.Body, 1<<16))
	return string(b), err
}

// measureSpeed downloads for up to five seconds and reports the rate.
func (e *Engine) measureSpeed(ctx context.Context, c *http.Client) float64 {
	for _, u := range []string{"https://sin-speed.hetzner.com/1GB.bin", "https://speed.cloudflare.com/__down?bytes=25000000"} {
		tctx, cancel := context.WithTimeout(ctx, 5*time.Second)
		req, _ := http.NewRequestWithContext(tctx, "GET", u, nil)
		start := time.Now()
		resp, err := c.Do(req)
		if err != nil {
			cancel()
			continue
		}
		n, _ := io.Copy(io.Discard, resp.Body)
		resp.Body.Close()
		cancel()
		if resp.StatusCode == 200 && n > 1<<20 {
			return float64(n) * 8 / 1e6 / time.Since(start).Seconds()
		}
	}
	e.Logs.Add("warn", "The speed test sites didn't respond, so download speed wasn't measured")
	return 0
}

// selfTest runs one full on, test, off cycle with no window, writing the result
// to selftest.json. It exists so the tunnel can be checked from a script.
func (e *Engine) selfTest() {
	e.Toggle()
	deadline := time.Now().Add(30 * time.Second)
	for time.Now().Before(deadline) && e.Status().State == string(StateConnecting) {
		time.Sleep(100 * time.Millisecond)
	}
	report := map[string]any{"status": e.Status()}
	if e.Status().State == string(StateOn) {
		time.Sleep(time.Second)
		report["test"] = e.Test()
		report["status"] = e.Status()
	}
	e.Stop("")
	report["logs"] = e.Logs.Since(0)
	b, _ := json.MarshalIndent(report, "", "  ")
	os.WriteFile(e.dir+`\selftest.json`, b, 0o600)
}
