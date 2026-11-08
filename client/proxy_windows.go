//go:build windows

package main

// Self-healing proxy safety net (Windows).
//
// The real danger with a system-wide proxy is a dead listener: if the client
// stops while the Windows proxy still points at 127.0.0.1:8080, every app loses
// internet until the setting is cleared. These layers make sure that can't last:
//
//  1. The client clears the proxy on any clean exit, Ctrl-C/close signal, or panic.
//  2. A detached guardian process watches this one; if it dies hard (crash,
//     taskkill /F) and nothing is listening on 8080, the guardian clears it.
//  3. (In the desktop app) a poll clears a stale proxy, and every launch heals
//     a leftover one.

import (
	"net"
	"os"
	"os/exec"
	"os/signal"
	"strconv"
	"strings"
	"syscall"
	"time"

	"golang.org/x/sys/windows"
	"golang.org/x/sys/windows/registry"
)

const regPath = `Software\Microsoft\Windows\CurrentVersion\Internet Settings`

var wininet = windows.NewLazyDLL("wininet.dll")

func refreshWinInet() {
	proc := wininet.NewProc("InternetSetOptionW")
	proc.Call(0, 39, 0, 0) // INTERNET_OPTION_SETTINGS_CHANGED
	proc.Call(0, 37, 0, 0) // INTERNET_OPTION_REFRESH
}

// proxyIsOurs reports whether the system proxy is currently set to our listener.
func proxyIsOurs() bool {
	k, err := registry.OpenKey(registry.CURRENT_USER, regPath, registry.QUERY_VALUE)
	if err != nil {
		return false
	}
	defer k.Close()
	en, _, _ := k.GetIntegerValue("ProxyEnable")
	srv, _, _ := k.GetStringValue("ProxyServer")
	return en == 1 && strings.Contains(srv, httpAddr)
}

func clearSystemProxy() {
	k, err := registry.OpenKey(registry.CURRENT_USER, regPath, registry.SET_VALUE)
	if err != nil {
		return
	}
	defer k.Close()
	k.SetDWordValue("ProxyEnable", 0)
	for _, v := range []string{"ProxyServer", "AutoConfigURL", "ProxyOverride"} {
		k.DeleteValue(v)
	}
	refreshWinInet()
}

// clearProxyIfOurs only touches the setting if it still points at us, so we
// never clobber an unrelated proxy the user configured.
func clearProxyIfOurs() {
	if proxyIsOurs() {
		clearSystemProxy()
		logln("system proxy cleared")
	}
}

// installExitCleanup clears the proxy on Ctrl-C, console close or SIGTERM.
func installExitCleanup() {
	ch := make(chan os.Signal, 1)
	signal.Notify(ch, os.Interrupt, syscall.SIGTERM)
	go func() {
		<-ch
		clearProxyIfOurs()
		os.Exit(0)
	}()
}

// spawnGuardian launches a detached copy of ourselves in --guard mode.
func spawnGuardian() {
	exe, err := os.Executable()
	if err != nil {
		return
	}
	cmd := exec.Command(exe, "--guard", strconv.Itoa(os.Getpid()))
	cmd.SysProcAttr = &syscall.SysProcAttr{
		HideWindow:    true,
		CreationFlags: 0x00000008 | 0x00000200, // DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
	}
	_ = cmd.Start()
	if cmd.Process != nil {
		_ = cmd.Process.Release()
	}
}

func isListening() bool {
	c, err := net.DialTimeout("tcp", httpAddr, 500*time.Millisecond)
	if err != nil {
		return false
	}
	c.Close()
	return true
}

func pidAlive(pid int) bool {
	h, err := windows.OpenProcess(windows.PROCESS_QUERY_LIMITED_INFORMATION, false, uint32(pid))
	if err != nil {
		return false
	}
	defer windows.CloseHandle(h)
	var code uint32
	if err := windows.GetExitCodeProcess(h, &code); err != nil {
		return false
	}
	return code == 259 // STILL_ACTIVE
}

// runGuardian waits for the parent client to vanish, gives a brief grace period
// for a restart to take over the port, and otherwise clears a stale proxy.
func runGuardian(args []string) {
	if len(args) < 3 {
		return
	}
	ppid, err := strconv.Atoi(args[2])
	if err != nil {
		return
	}

	for pidAlive(ppid) {
		time.Sleep(time.Second)
	}

	// The parent is gone. Wait a few seconds: the desktop app may be relaunching
	// a fresh client that will take the port back over.
	for i := 0; i < 10; i++ {
		time.Sleep(500 * time.Millisecond)
		if isListening() {
			return // a new client took over — nothing to heal
		}
	}

	if proxyIsOurs() && !isListening() {
		clearSystemProxy()
	}
}
