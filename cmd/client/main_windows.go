// Command client is the Windows app. Administrator rights are requested by the
// manifest because creating a network adapter and changing routes requires them.
package main

import (
	"crypto/sha256"
	_ "embed"
	"encoding/hex"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"runtime/debug"
	"slices"
	"strconv"
	"time"

	webview2 "github.com/jchv/go-webview2"
	"golang.org/x/sys/windows"
	"golang.org/x/sys/windows/registry"
)

// Set at build time by build.ps1, from secrets.env.
var (
	serverURL  string
	proxyToken string
)

//go:embed ui.html
var uiHTML string

func main() {
	dir := filepath.Join(os.Getenv("LOCALAPPDATA"), "FortiProxy")
	os.MkdirAll(dir, 0o700)
	if f, err := os.OpenFile(filepath.Join(dir, "app.log"), os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o600); err == nil {
		log.SetOutput(f)
		debug.SetCrashOutput(f, debug.CrashOptions{})
	}

	if len(os.Args) == 3 && os.Args[1] == "--watchdog" {
		if pid, err := strconv.Atoi(os.Args[2]); err == nil {
			watchdog(dir, pid)
		}
		return
	}
	if slices.Contains(os.Args, "--repair") {
		appendRecovery(dir, repairNetwork(dir))
		return
	}

	name, _ := windows.UTF16PtrFromString(`Local\FortiProxySingleInstance`)
	if _, err := windows.CreateMutex(nil, false, name); err == windows.ERROR_ALREADY_EXISTS {
		if !slices.Contains(os.Args, "--selftest") {
			alert("FortiProxy is already running.")
		}
		return
	}

	engine := NewEngine(dir)
	for _, note := range takeRecoveryNotes(dir) {
		engine.Logs.Add("warn", "%s", note)
	}
	// Reaching this point with the marker set means the app and its watchdog
	// both died while connected.
	if wasActive(dir) {
		engine.Logs.Add("warn", "The last session ended unexpectedly. %s", repairNetwork(dir))
	}
	if err := startWatchdog(); err != nil {
		engine.Logs.Add("warn", "The crash watchdog didn't start: %v", err)
	}
	if slices.Contains(os.Args, "--selftest") {
		engine.selfTest()
		return
	}
	if slices.Contains(os.Args, "--hold") {
		engine.Toggle() // connects and waits to be killed, for crash testing
		select {}
	}

	width, height := windowSize()
	w := webview2.NewWithOptions(webview2.WebViewOptions{
		DataPath:  filepath.Join(dir, "webview"),
		AutoFocus: true,
		WindowOptions: webview2.WindowOptions{
			Title: "FortiProxy", Width: uint(width), Height: uint(height), IconId: 1, Center: true,
		},
	})
	if w == nil {
		alert("This app needs the Microsoft Edge WebView2 runtime.")
		return
	}
	defer w.Destroy()

	w.SetSize(width, height, webview2.HintFixed)
	// These names are prefixed on purpose. Plain ones can collide with built-in
	// browser properties: window.status silently turns a function into a string.
	w.Bind("proxyToggle", func() { engine.Toggle() })
	w.Bind("proxyReconnect", func() { engine.Reconnect() })
	w.Bind("proxyStatus", func() Status { return engine.Status() })
	w.Bind("proxyLogs", func(since uint64) []LogEntry { return engine.Logs.Since(since) })
	w.Bind("proxyClearLogs", func() { engine.Logs.Clear() })
	w.Bind("proxySettings", func() Settings { return engine.Settings() })
	w.Bind("proxySaveSettings", func(s Settings) error { return engine.SetSettings(s) })
	w.Bind("proxyStartTest", func() { engine.StartTest() })
	w.Bind("proxyRepair", func() { engine.Repair() })
	w.Bind("proxyAbout", func() map[string]string {
		return map[string]string{"version": appVersion, "developer": developer, "repo": repoURL()}
	})
	w.Bind("proxyOpenRepo", func() { openURL(repoURL()) })
	w.Bind("proxyCheckUpdate", func() UpdateCheck { return checkUpdate() })
	w.Bind("proxyApplyUpdate", func() error { return applyUpdate(engine) })
	w.Bind("proxyUninstall", func() { go uninstall(engine) })
	w.Bind("proxyViewport", func(width, height int, scale float64, zoom float64) {
		engine.Logs.Add("info", "Window ready: %dx%d, display scale %.2f, Home zoom %.2f", width, height, scale, zoom)
	})
	w.SetHtml(uiHTML)
	engine.Logs.Add("info", "App started on %s (%s)", deviceName(), appVersion)
	// Look for a newer published version in the background. It only prompts if
	// one exists, and does nothing otherwise.
	go checkForUpdate(engine)
	if engine.Settings().AutoConnect {
		engine.Toggle()
	}
	w.Run()

	// The window is gone: put the computer's networking back before exiting. If
	// that hangs, exit anyway, because Windows and the watchdog finish the job.
	stopped := make(chan struct{})
	go func() {
		engine.Stop("")
		close(stopped)
	}()
	select {
	case <-stopped:
	case <-time.After(8 * time.Second):
		log.Printf("shutdown timed out")
	}
}

// windowSize returns the window's size in physical pixels. The app is DPI aware,
// so Windows doesn't scale these numbers for it: without this, a display set to
// 150% would give the page only two thirds of the room asked for.
func windowSize() (width, height int) {
	const logicalWidth, logicalHeight = 520, 880
	user32 := windows.NewLazySystemDLL("user32.dll")
	dpi, _, _ := user32.NewProc("GetDpiForSystem").Call()
	if dpi == 0 {
		dpi = 96
	}
	width = logicalWidth * int(dpi) / 96
	height = logicalHeight * int(dpi) / 96
	const smCyFullScreen = 17 // usable height, excluding the taskbar and title bar
	if usable, _, _ := user32.NewProc("GetSystemMetrics").Call(smCyFullScreen); usable > 0 && height > int(usable) {
		height = int(usable)
	}
	return width, height
}

func alert(msg string) {
	text, _ := windows.UTF16PtrFromString(msg)
	title, _ := windows.UTF16PtrFromString("FortiProxy")
	windows.MessageBox(0, text, title, windows.MB_OK|windows.MB_ICONINFORMATION)
}

// deviceID is stable across reinstalls and reveals nothing about the machine.
func deviceID() string {
	k, err := registry.OpenKey(registry.LOCAL_MACHINE, `SOFTWARE\Microsoft\Cryptography`, registry.QUERY_VALUE|registry.WOW64_64KEY)
	if err == nil {
		defer k.Close()
		if guid, _, err := k.GetStringValue("MachineGuid"); err == nil {
			sum := sha256.Sum256([]byte("fortiproxy:" + guid))
			return hex.EncodeToString(sum[:16])
		}
	}
	return "host-" + deviceName()
}

func deviceName() string {
	name, err := os.Hostname()
	if err != nil {
		return "Windows PC"
	}
	return name
}

func deviceOS() string {
	v := windows.RtlGetVersion()
	if v.MajorVersion == 10 && v.BuildNumber >= 22000 {
		return fmt.Sprintf("Windows 11 (build %d)", v.BuildNumber)
	}
	return fmt.Sprintf("Windows %d (build %d)", v.MajorVersion, v.BuildNumber)
}
