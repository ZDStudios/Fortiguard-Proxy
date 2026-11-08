# Custom Proxy API

This guide explains how to build your own app on Custom Proxy. There are two
separate interfaces:

| | Tunnel | Dashboard API |
|---|---|---|
| **Use it to** | Send traffic through the proxy | Read stats, and kick or ban devices |
| **Address** | `wss://proxy.zdstudios.network/tunnel` | `https://proxy.zdstudios.network/api/...` |
| **Sign in with** | `PROXY_TOKEN` | `DASHBOARD_PASSWORD` |

Your real values are in `API-KEYS.local.md` and `secrets.env`. Both stay on your
PC and out of Git. This guide uses placeholders so it's safe to share.

## Before you start

**This isn't a normal proxy address.** The server has no SOCKS or HTTP proxy port,
so you can't paste it into a browser's proxy settings, curl's `--proxy` option or
Postman. A program has to speak the tunnel protocol below.

**Your app can't import this project's Go code.** The packages are under
`internal/`, which Go blocks from other projects. Use the example below, which
needs only two public libraries.

**A website can't use the tunnel.** Browsers don't let JavaScript set the
`Authorization` header on a WebSocket, and anyone could read the token from your
page. Use a desktop app, a mobile app or a backend service.

**Keep the token private.** Anyone who has it can send traffic through your
server. It's one shared token, built into every copy of your app, so treat
anything you ship that contains it as a secret too.

## Tunnel quick start in Go

This complete program fetches a page through the proxy and looks up a domain over
UDP. It has been run against the live server.

```bash
go mod init myapp
go get github.com/coder/websocket github.com/hashicorp/yamux
```

Save it as `main.go`, then run it with your token:

```bash
PROXY_TOKEN=your-token-here go run .
```

In PowerShell, use this instead:

```powershell
$env:PROXY_TOKEN = 'your-token-here'; go run .
```

```go
// A standalone client for Custom Proxy.
package main

import (
	"context"
	"crypto/tls"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/coder/websocket"
	"github.com/hashicorp/yamux"
)

const (
	serverURL = "wss://proxy.zdstudios.network/tunnel"
	netTCP    = 1
	netUDP    = 2
)

// connect logs in and returns a session that carries any number of streams.
func connect(ctx context.Context, token, deviceID, deviceName string) (*yamux.Session, error) {
	headers := http.Header{}
	headers.Set("Authorization", "Bearer "+token)
	headers.Set("X-Device-Id", deviceID)
	headers.Set("X-Device-Name", deviceName)
	headers.Set("X-Device-Os", "My App")

	ws, resp, err := websocket.Dial(ctx, serverURL, &websocket.DialOptions{
		HTTPHeader:      headers,
		CompressionMode: websocket.CompressionDisabled,
	})
	if err != nil {
		if resp != nil {
			return nil, fmt.Errorf("refused (%d): %s", resp.StatusCode, resp.Header.Get("X-Proxy-Refusal"))
		}
		return nil, err
	}
	ws.SetReadLimit(-1)

	// Keep this context alive for as long as the session: cancelling it closes
	// the connection.
	conn := websocket.NetConn(context.Background(), ws, websocket.MessageBinary)
	cfg := yamux.DefaultConfig()
	cfg.MaxStreamWindowSize = 16 << 20 // the default of 256 KiB limits speed
	cfg.LogOutput = io.Discard
	return yamux.Client(conn, cfg)
}

// open asks the server to connect to a destination and waits for its answer.
func open(s *yamux.Session, network byte, host string, port uint16) (net.Conn, error) {
	st, err := s.OpenStream()
	if err != nil {
		return nil, err
	}
	header := []byte{network, byte(len(host))}
	header = append(header, host...)
	header = binary.BigEndian.AppendUint16(header, port)
	if _, err := st.Write(header); err != nil {
		st.Close()
		return nil, err
	}
	var status [1]byte
	if _, err := io.ReadFull(st, status[:]); err != nil {
		st.Close()
		return nil, err
	}
	if status[0] != 0 {
		st.Close()
		return nil, errors.New("the server couldn't reach " + host)
	}
	return st, nil
}

func fetchTrace(s *yamux.Session) (string, error) {
	const host = "www.cloudflare.com"
	st, err := open(s, netTCP, host, 443)
	if err != nil {
		return "", err
	}
	defer st.Close()
	conn := tls.Client(st, &tls.Config{ServerName: host})
	fmt.Fprintf(conn, "GET /cdn-cgi/trace HTTP/1.1\r\nHost: %s\r\nConnection: close\r\n\r\n", host)
	body, err := io.ReadAll(conn)
	if err != nil && len(body) == 0 {
		return "", err
	}
	return string(body), nil
}

// lookup sends one DNS query over UDP. Each datagram has a 2-byte length prefix.
func lookup(s *yamux.Session, name string) (int, error) {
	st, err := open(s, netUDP, "1.1.1.1", 53)
	if err != nil {
		return 0, err
	}
	defer st.Close()
	q := []byte{0x12, 0x34, 1, 0, 0, 1, 0, 0, 0, 0, 0, 0}
	for _, label := range strings.Split(name, ".") {
		q = append(append(q, byte(len(label))), label...)
	}
	q = append(q, 0, 0, 1, 0, 1) // type A, class IN

	packet := binary.BigEndian.AppendUint16(nil, uint16(len(q)))
	if _, err := st.Write(append(packet, q...)); err != nil {
		return 0, err
	}
	var size [2]byte
	if _, err := io.ReadFull(st, size[:]); err != nil {
		return 0, err
	}
	reply := make([]byte, binary.BigEndian.Uint16(size[:]))
	_, err = io.ReadFull(st, reply)
	return len(reply), err
}

func main() {
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	s, err := connect(ctx, os.Getenv("PROXY_TOKEN"), "my-app-1", "My App")
	if err != nil {
		fmt.Println("connect failed:", err)
		os.Exit(1)
	}
	defer s.Close()

	trace, err := fetchTrace(s)
	if err != nil {
		fmt.Println("fetch failed:", err)
		os.Exit(1)
	}
	for _, line := range strings.Split(trace, "\n") {
		if strings.HasPrefix(line, "ip=") {
			fmt.Println("exit", line)
		}
	}
	n, err := lookup(s, "example.com")
	fmt.Println("udp dns reply bytes:", n, "err:", err)
	if _, err := open(s, netTCP, "127.0.0.1", 8080); err != nil {
		fmt.Println("private address refused:", err)
	}
}
```

Expected output, with your server's address as the exit IP:

```text
exit ip=179.197.241.150
udp dns reply bytes: 61 err: <nil>
private address refused: the server couldn't reach 127.0.0.1
```

## Tunnel protocol

Use this section to build a client in another language. The layers are:

```text
your data
yamux streams        many connections share one link
WebSocket, binary    GET /tunnel
TLS                  port 443
```

### 1. Open the WebSocket

Connect to `wss://proxy.zdstudios.network/tunnel` with these headers. Turn off
WebSocket compression, and send everything as binary messages.

| Header | Required | Value |
|---|---|---|
| `Authorization` | Yes | `Bearer <PROXY_TOKEN>` |
| `X-Device-Id` | Yes | A stable ID, unique to this device |
| `X-Device-Name` | No | The name shown on the dashboard, up to 64 characters |
| `X-Device-Os` | No | The system shown on the dashboard |

Keep the device ID the same between runs. Kicks and bans apply to it, and a new ID
appears as a new device.

| Response | Meaning | What your app should do |
|---|---|---|
| `101` | Connected | Start yamux |
| `400` | `X-Device-Id` is missing | Fix your code |
| `401` | Wrong token | Stop, and don't retry |
| `403` | Kicked, turned off or banned | Stop, and show the `X-Proxy-Refusal` header to the user |

### 2. Start yamux

Treat the WebSocket as a byte stream and run a yamux client over it. Your app is
the client, and it opens every stream. WebSocket message boundaries mean nothing,
because yamux frames can span messages.

- Set the maximum stream window to 16 MiB. The default 256 KiB limits speed.
- Turn on keepalive, with a 15-second interval.

The format is in the
[yamux specification](https://github.com/hashicorp/yamux/blob/master/spec.md).

### 3. Open a connection

Each connection you make through the proxy is one yamux stream. Start each stream
by sending this header in one write. Numbers are big-endian.

| Bytes | Field | Value |
|---|---|---|
| 1 | Network | `1` for TCP, `2` for UDP |
| 1 | Host length | 1 to 255 |
| Varies | Host | A hostname or IP address, with no brackets around IPv6 |
| 2 | Port | Destination port |

For example, a TCP connection to `example.com:443`:

```text
01 0b 65 78 61 6d 70 6c 65 2e 63 6f 6d 01 bb
```

The server then sends one status byte, after it has tried the destination:

| Status | Meaning |
|---|---|
| `0` | Connected, so start sending data |
| `1` | Failed. The server gives no reason, and the stream is finished. |

Wait for this byte before you send data. The server closes the stream if the
header doesn't arrive within 15 seconds.

### 4. Send data

**TCP:** send raw bytes both ways. Closing your side of a yamux stream sends a FIN,
and you can keep reading the reply until the other side closes.

**UDP:** each packet has a 2-byte big-endian length in front of it, in both
directions. The largest packet is 65,535 bytes. A UDP stream closes after 2 minutes
with no traffic.

### 5. Reconnect

- If the link drops, reconnect with a growing delay, such as 200 ms up to 5 seconds.
- Connections that were open when it dropped are lost, so your app must reopen them.
- Don't retry after a `401` or `403`.
- Several links share traffic better than one. The official app uses 4, which
  stops one lost packet from stalling everything.

### Limits

| Limit | Value |
|---|---|
| Open streams per device | 2,048 |
| Time for the server to connect to a TCP destination | 10 seconds |
| Time for a UDP destination to be set up | 5 seconds |
| Protocols | TCP and UDP only, so ping doesn't work |
| Destinations | Public internet only |

Private addresses are refused, including `127.0.0.1`, `10.x`, `172.16-31.x`,
`192.168.x`, `100.64.x` and `169.254.x`. This keeps devices away from the other
apps on your server. IPv6 destinations fail if your server has no IPv6.

### Other languages

Any language with TLS WebSockets and a yamux library can do this. Only the Go
libraries above have been tested with this server. Others to look at:

| Language | yamux library |
|---|---|
| Rust | `yamux` |
| JavaScript on Node.js | `yamux-js` |
| Python | No widely used option, so run a small Go helper beside your app |

Check that a library works with HashiCorp's yamux before you depend on it. Some
are built for libp2p.

## Dashboard API

You can use this to build your own admin tool. Sign in with the dashboard password
to get a cookie, which lasts 30 days. It's a session cookie for the dashboard
itself, and the server doesn't send CORS headers, so call it from a backend or
desktop app.

```bash
curl -c cookies.txt -H "Content-Type: application/json" \
  -d '{"password":"your-password-here"}' \
  https://proxy.zdstudios.network/api/login
```

Then send the cookie with each request:

```bash
curl -b cookies.txt "https://proxy.zdstudios.network/api/state?span=1h"
```

Keep `cookies.txt` private, because it works like the password.

### Endpoints

| Method | Path | What it does |
|---|---|---|
| `GET` | `/healthz` | Returns `ok`, with no sign-in needed |
| `POST` | `/api/login` | Signs in with `{"password":"..."}` |
| `POST` | `/api/logout` | Clears the cookie in the response |
| `GET` | `/api/state` | Returns all live stats |
| `GET` | `/api/devices/{id}/history` | Returns the sites a device has used |
| `POST` | `/api/devices/{id}/{action}` | Controls a device |

Calls without a valid cookie return `401`. A wrong password also returns `401`.

### Device actions

Send a `POST` to `/api/devices/{id}/{action}`. Success returns `204` with no body.
A `404` means the device doesn't exist or the action isn't allowed.

| Action | Body | Effect |
|---|---|---|
| `kick` | None | Disconnects now, and refuses it for 1 minute |
| `disable` | `{"minutes":60}` | Turns it off. `0` means until you enable it. |
| `enable` | None | Turns it back on |
| `ban` | None | Disconnects it and refuses it until unbanned |
| `unban` | None | Lifts the ban |
| `rename` | `{"name":"New name"}` | Changes the name on the dashboard |
| `remove` | None | Deletes it and its history. Refused if it's online or banned. |

```bash
curl -b cookies.txt -X POST -H "Content-Type: application/json" \
  -d '{"minutes":60}' \
  https://proxy.zdstudios.network/api/devices/DEVICE_ID/disable
```

URL-encode the device ID if it contains special characters.

### `GET /api/state`

| Parameter | Value |
|---|---|
| `device` | A device ID, to limit the stats to it. Leave it out for all devices. |
| `span` | `5m` (default), `1h` or `24h`, which sets the range of `series` |

| Field | Contents |
|---|---|
| `now` | Server time |
| `online` | Number of devices online |
| `total` | Combined `up`, `down`, `rateUp`, `rateDown` and `conns` |
| `day` | Bytes used in the last 24 hours |
| `series` | Speed points: `t` (Unix time), `up` and `down` in bytes per second |
| `devices` | Every device, as shown below |
| `active` | Up to 200 open connections, busiest first |
| `recent` | Up to 100 recently closed connections |
| `hosts` | Up to 50 top sites: `host`, `up`, `down`, `conns`, `last` |
| `kinds` | Bytes by type: `HTTPS`, `HTTP`, `UDP`, `DNS`, `Other` |
| `events` | Up to 40 activity items: `time`, `kind`, `device`, `deviceId` |
| `server` | `uptime` in seconds, `memMB`, `goroutines` |

Each item in `devices` has:

| Field | Contents |
|---|---|
| `id`, `name`, `os`, `ip` | Identity |
| `online` | Whether it's connected now |
| `blocked` | `true` if it's banned |
| `disabled`, `kicked` | Whether it's turned off, and whether that came from a kick |
| `disabledUntil` | When a timed turn-off ends, if there is one |
| `firstSeen`, `lastSeen` | Timestamps |
| `up`, `down` | All-time bytes |
| `rateUp`, `rateDown` | Current bytes per second |
| `conns` | Open connections |
| `day` | Bytes in the last 24 hours |
| `spark` | Bytes per second over the last minute |

Items in `active` and `recent` have `id`, `device`, `deviceId`, `network`, `host`,
`addr`, `port`, `started`, `up` and `down`. Closed connections also have `ended`.

Site totals in the all-devices view can be up to 5 seconds old. There's no need to
poll faster than once a second.

### `GET /api/devices/{id}/history`

| Parameter | Value |
|---|---|
| `q` | Only sites containing this text, ignoring case |
| `before` | A Unix time. Returns older entries. Leave it out for the newest. |

```json
{
  "entries": [
    { "t": 1793957760, "host": "github.com", "port": 443, "net": "TCP",
      "up": 1740, "down": 104520, "conns": 3 }
  ],
  "more": true
}
```

Entries are newest first, about 200 at a time, and grouped by the minute. For the
next page, send the last entry's `t` as `before` while `more` is `true`.

History shows site names and data used. It never shows page contents or search
terms, because those are encrypted.

## Changing the token

1. Change `PROXY_TOKEN` in `secrets.env`.
2. Change it to match in the app's environment variables in Coolify, then redeploy.
3. Run `.\build.ps1` to rebuild `CustomProxy.exe`.
4. Update your own apps.

Every older copy stops connecting straight away, so install the new builds on all
your devices. `API-KEYS.local.md` won't update by itself, so edit it too.

The dashboard password works the same way, without steps 3 and 4. It must be at
least 8 characters, and the token at least 32.

## Everything shows on your dashboard

Your app's connections appear like any other device, under the name it sends.
Sites it uses go in that device's history, and Kick, Turn off and Ban all work on
it.
