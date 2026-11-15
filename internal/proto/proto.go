// Package proto is the wire format shared by the client and the server.
//
// One device holds several WebSocket connections to the server, and each one
// carries a yamux session. Every proxied connection is one yamux stream:
//
//	client -> server   target header (network, host, port)
//	server -> client   one status byte, sent after the real destination answers
//	both ways          raw TCP bytes, or length-prefixed UDP datagrams
package proto

import (
	"encoding/binary"
	"errors"
	"io"
	"time"

	"github.com/hashicorp/yamux"
)

const (
	TunnelPath = "/tunnel"

	HeaderDeviceID   = "X-Device-Id"
	HeaderDeviceName = "X-Device-Name"
	HeaderDeviceOS   = "X-Device-Os"
	HeaderRefusal    = "X-Proxy-Refusal" // why the server turned a device away

	NetTCP byte = 1
	NetUDP byte = 2

	StatusOK   byte = 0
	StatusFail byte = 1

	MaxDatagram = 65535
)

// Target says where a stream should be connected.
type Target struct {
	Net  byte
	Host string
	Port uint16
}

// WriteTarget sends the stream header in a single write.
func WriteTarget(w io.Writer, t Target) error {
	if len(t.Host) == 0 || len(t.Host) > 255 {
		return errors.New("invalid target host")
	}
	b := make([]byte, 0, 4+len(t.Host))
	b = append(b, t.Net, byte(len(t.Host)))
	b = append(b, t.Host...)
	b = binary.BigEndian.AppendUint16(b, t.Port)
	_, err := w.Write(b)
	return err
}

// ReadTarget reads the stream header.
func ReadTarget(r io.Reader) (Target, error) {
	var head [2]byte
	if _, err := io.ReadFull(r, head[:]); err != nil {
		return Target{}, err
	}
	if head[0] != NetTCP && head[0] != NetUDP {
		return Target{}, errors.New("invalid target network")
	}
	if head[1] == 0 {
		return Target{}, errors.New("empty target host")
	}
	rest := make([]byte, int(head[1])+2)
	if _, err := io.ReadFull(r, rest); err != nil {
		return Target{}, err
	}
	n := len(rest) - 2
	return Target{Net: head[0], Host: string(rest[:n]), Port: binary.BigEndian.Uint16(rest[n:])}, nil
}

// WriteDatagram sends one UDP packet in a single write.
func WriteDatagram(w io.Writer, p []byte) error {
	if len(p) > MaxDatagram {
		return errors.New("datagram too large")
	}
	b := make([]byte, 2+len(p))
	binary.BigEndian.PutUint16(b, uint16(len(p)))
	copy(b[2:], p)
	_, err := w.Write(b)
	return err
}

// ReadDatagram reads one UDP packet into buf, which must hold MaxDatagram bytes.
func ReadDatagram(r io.Reader, buf []byte) (int, error) {
	var head [2]byte
	if _, err := io.ReadFull(r, head[:]); err != nil {
		return 0, err
	}
	n := int(binary.BigEndian.Uint16(head[:]))
	if _, err := io.ReadFull(r, buf[:n]); err != nil {
		return 0, err
	}
	return n, nil
}

// YamuxConfig is used by both ends. The large stream window is what allows
// fast downloads: yamux's 256 KiB default caps a stream at a few MB/s on a
// connection with ordinary latency.
func YamuxConfig() *yamux.Config {
	c := yamux.DefaultConfig()
	c.AcceptBacklog = 2048
	c.EnableKeepAlive = true
	c.KeepAliveInterval = 15 * time.Second
	c.ConnectionWriteTimeout = 20 * time.Second
	c.MaxStreamWindowSize = 16 << 20
	c.StreamOpenTimeout = 30 * time.Second
	c.StreamCloseTimeout = time.Minute
	c.LogOutput = io.Discard
	return c
}
