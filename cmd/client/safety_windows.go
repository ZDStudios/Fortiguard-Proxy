package main

import (
	"encoding/json"
	"fmt"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"time"

	"golang.org/x/sys/windows"
)

// Crash safety, in layers. The app only ever changes its own virtual adapter:
// it never touches the Wi-Fi or Ethernet driver or their settings.
//
//  1. Windows: the adapter, its routes and its firewall filters are all tied to
//     the app's process, so Windows removes them when the process dies.
//  2. Watchdog: a small second process waits for the app to exit. If the app
//     died while connected, it removes anything left behind.
//  3. Next launch: if the watchdog was killed too, the app repairs on startup.
//  4. Repair network: a button in Settings, and FortiProxy.exe --repair.
//
// The marker file means "the network is changed right now". It is written just
// before the adapter is created and removed once everything is restored, so its
// presence after an exit means the exit wasn't clean.
const markerName = "active.json"

func markActive(dir string) error {
	b, _ := json.Marshal(map[string]any{"pid": os.Getpid(), "started": time.Now()})
	return os.WriteFile(filepath.Join(dir, markerName), b, 0o600)
}

func clearActive(dir string) { os.Remove(filepath.Join(dir, markerName)) }

func wasActive(dir string) bool {
	_, err := os.Stat(filepath.Join(dir, markerName))
	return err == nil
}

// startWatchdog launches the watchdog for this process.
func startWatchdog() error {
	self, err := os.Executable()
	if err != nil {
		return err
	}
	cmd := exec.Command(self, "--watchdog", strconv.Itoa(os.Getpid()))
	cmd.SysProcAttr = &syscall.SysProcAttr{
		HideWindow:    true,
		CreationFlags: windows.CREATE_NO_WINDOW | windows.CREATE_NEW_PROCESS_GROUP | windows.CREATE_BREAKAWAY_FROM_JOB,
	}
	if err := cmd.Start(); err != nil {
		return err
	}
	return cmd.Process.Release()
}

// watchdog waits for the app to exit, then cleans up if it died while connected.
func watchdog(dir string, pid int) {
	h, err := windows.OpenProcess(windows.SYNCHRONIZE, false, uint32(pid))
	if err != nil {
		return
	}
	defer windows.CloseHandle(h)
	windows.WaitForSingleObject(h, windows.INFINITE)
	time.Sleep(500 * time.Millisecond) // give Windows a moment to tear things down
	if wasActive(dir) {
		report := repairNetwork(dir)
		appendRecovery(dir, "The app stopped unexpectedly while connected. "+report)
	}
}

func appendRecovery(dir, text string) {
	f, err := os.OpenFile(filepath.Join(dir, "recovery.log"), os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600)
	if err != nil {
		return
	}
	defer f.Close()
	fmt.Fprintf(f, "%s %s\n", time.Now().Format("2006-01-02 15:04:05"), text)
}

// takeRecoveryNotes returns anything the watchdog recorded since the last launch.
func takeRecoveryNotes(dir string) []string {
	path := filepath.Join(dir, "recovery.log")
	b, err := os.ReadFile(path)
	if err != nil {
		return nil
	}
	os.Remove(path)
	return strings.Split(strings.TrimSpace(string(b)), "\n")
}

func hidden(name string, args ...string) *exec.Cmd {
	cmd := exec.Command(name, args...)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: windows.CREATE_NO_WINDOW}
	return cmd
}

func adapterExists() bool {
	_, err := net.InterfaceByName(adapterName)
	return err == nil
}

// repairNetwork removes anything this app could have left behind and returns a
// sentence saying what it found. It is safe to run at any time the proxy is off.
func repairNetwork(dir string) string {
	lock, _ := windows.UTF16PtrFromString(`Local\FortiProxyRepair`)
	if m, err := windows.CreateMutex(nil, false, lock); err == nil {
		defer windows.CloseHandle(m)
		windows.WaitForSingleObject(m, 20000)
		defer windows.ReleaseMutex(m)
	}
	found := adapterExists()
	if found {
		removeAdapter()
	}
	hidden("ipconfig", "/flushdns").Run()
	clearActive(dir)
	switch {
	case found && adapterExists():
		return "The leftover adapter was switched off, so it can't carry traffic. Restarting Windows will remove it."
	case found:
		return "A leftover adapter was removed and your normal network is restored."
	}
	return "Nothing was left behind, and your normal network is intact."
}

// removeAdapter removes the virtual adapter by device ID. If Windows refuses,
// disabling it has the same effect on traffic: its routes stop applying.
func removeAdapter() {
	script := fmt.Sprintf(`(Get-NetAdapter -Name '%s' -ErrorAction SilentlyContinue).PnPDeviceID`, adapterName)
	out, err := hidden("powershell", "-NoProfile", "-NonInteractive", "-Command", script).Output()
	if id := strings.TrimSpace(string(out)); err == nil && id != "" {
		hidden("pnputil", "/remove-device", id).Run()
	}
	for i := 0; i < 10 && adapterExists(); i++ {
		time.Sleep(200 * time.Millisecond)
	}
	if adapterExists() {
		hidden("netsh", "interface", "set", "interface", "name="+adapterName, "admin=disabled").Run()
	}
}
