package main

import (
	"archive/zip"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

	"golang.org/x/sys/windows"
)

// appVersion is baked in at build time by build.ps1 from docs/version.txt
// (e.g. "V28"). It is what the updater compares against the published version.
var appVersion = "dev"

// pendingVersion holds the newer version the launch check found, if any. The
// window polls it (proxyPendingUpdate) and shows the update prompt.
var (
	pendingMu      sync.Mutex
	pendingVersion string
)

func setPendingUpdate(v string) { pendingMu.Lock(); pendingVersion = v; pendingMu.Unlock() }

func pendingUpdate() string { pendingMu.Lock(); defer pendingMu.Unlock(); return pendingVersion }

const (
	updateRepo = "ZDStudios/Fortiguard-Proxy"
	developer  = "ZD Studios"
)

// The version file and the matching release zip both live in the repo root on
// the main branch, served raw by GitHub — the same contract older installs use,
// so every version can update to the next one.
func repoURL() string { return "https://github.com/" + updateRepo }

// versionURL carries a unique query each call so it defeats
// raw.githubusercontent.com's ~5 minute CDN cache — an update is then seen as
// soon as it is published, not up to 5 minutes later.
func versionURL() string {
	return fmt.Sprintf("https://raw.githubusercontent.com/%s/main/docs/version.txt?nocache=%d", updateRepo, time.Now().UnixNano())
}
func zipURL(v string) string {
	return "https://raw.githubusercontent.com/" + updateRepo + "/main/FortiProxy-" + v + ".zip"
}

// versionNum turns "V28" (or "v28", " 28 ") into 28 so versions can be compared.
func versionNum(v string) int {
	v = strings.TrimPrefix(strings.ToUpper(strings.TrimSpace(v)), "V")
	n, _ := strconv.Atoi(strings.TrimSpace(v))
	return n
}

// UpdateCheck is the result the Settings "Check for updates" button receives.
type UpdateCheck struct {
	Current   string `json:"current"`
	Latest    string `json:"latest"`
	Available bool   `json:"available"`
	Error     string `json:"error"`
}

func fetchLatestVersion() (string, error) {
	client := &http.Client{Timeout: 15 * time.Second}
	req, err := http.NewRequest("GET", versionURL(), nil)
	if err != nil {
		return "", err
	}
	// Belt and braces with the cache-busting query above.
	req.Header.Set("Cache-Control", "no-cache")
	req.Header.Set("Pragma", "no-cache")
	resp, err := client.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return "", fmt.Errorf("the server returned HTTP %d", resp.StatusCode)
	}
	b, _ := io.ReadAll(io.LimitReader(resp.Body, 64))
	return strings.TrimSpace(string(b)), nil
}

// checkUpdate reports whether a newer version is published (for the Settings UI).
func checkUpdate() UpdateCheck {
	r := UpdateCheck{Current: appVersion}
	latest, err := fetchLatestVersion()
	if err != nil {
		r.Error = err.Error()
		return r
	}
	r.Latest = latest
	r.Available = versionNum(latest) > versionNum(appVersion)
	return r
}

// applyUpdate (the Settings "Update now" button) downloads the latest published
// version and hands off to install.bat. On success the process exits and does
// not return; install.bat then relaunches the new build.
func applyUpdate(engine *Engine) error {
	latest, err := fetchLatestVersion()
	if err != nil {
		return err
	}
	if versionNum(latest) <= versionNum(appVersion) {
		return nil
	}
	return downloadAndInstall(engine, latest)
}

// checkForUpdate runs at launch: if a newer version is published it records it,
// so the window can show the "update available" prompt. It changes nothing on
// its own — the user decides from the prompt.
func checkForUpdate(engine *Engine) {
	defer func() { _ = recover() }()
	latest, err := fetchLatestVersion()
	if err != nil {
		engine.Logs.Add("info", "Update check skipped: %v", err)
		return
	}
	if versionNum(latest) > versionNum(appVersion) {
		engine.Logs.Add("warn", "A new version is available: %s (you have %s)", latest, appVersion)
		setPendingUpdate(latest)
	}
}

func downloadAndInstall(engine *Engine, latest string) error {
	engine.Logs.Add("info", "Downloading FortiProxy %s...", latest)
	client := &http.Client{Timeout: 5 * time.Minute}
	resp, err := client.Get(zipURL(latest))
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return fmt.Errorf("the download returned HTTP %d", resp.StatusCode)
	}

	tmp := filepath.Join(os.TempDir(), "FortiProxy-update-"+latest)
	os.RemoveAll(tmp)
	if err := os.MkdirAll(tmp, 0o700); err != nil {
		return err
	}
	zipPath := filepath.Join(tmp, "update.zip")
	out, err := os.Create(zipPath)
	if err != nil {
		return err
	}
	if _, err := io.Copy(out, resp.Body); err != nil {
		out.Close()
		return err
	}
	out.Close()

	if err := unzip(zipPath, tmp); err != nil {
		return err
	}
	bat := filepath.Join(tmp, "install.bat")
	if _, err := os.Stat(bat); err != nil {
		return fmt.Errorf("the update is missing install.bat")
	}

	// Put the network back before we quit, so nothing is left behind while
	// install.bat swaps the exe and relaunches it.
	engine.Stop("")
	engine.Logs.Add("info", "Installing the update...")

	cmd := exec.Command("cmd", "/c", bat)
	cmd.Dir = tmp
	cmd.SysProcAttr = &syscall.SysProcAttr{
		HideWindow:    true,
		CreationFlags: windows.CREATE_NO_WINDOW | windows.CREATE_NEW_PROCESS_GROUP | windows.CREATE_BREAKAWAY_FROM_JOB,
	}
	if err := cmd.Start(); err != nil {
		return err
	}
	cmd.Process.Release()
	time.Sleep(400 * time.Millisecond)
	os.Exit(0)
	return nil
}

func unzip(src, dest string) error {
	r, err := zip.OpenReader(src)
	if err != nil {
		return err
	}
	defer r.Close()
	for _, f := range r.File {
		// Guard against path traversal from a crafted archive.
		target := filepath.Join(dest, f.Name)
		if !strings.HasPrefix(target, filepath.Clean(dest)+string(os.PathSeparator)) {
			return fmt.Errorf("unsafe path in archive: %s", f.Name)
		}
		if f.FileInfo().IsDir() {
			os.MkdirAll(target, 0o700)
			continue
		}
		os.MkdirAll(filepath.Dir(target), 0o700)
		rc, err := f.Open()
		if err != nil {
			return err
		}
		w, err := os.OpenFile(target, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0o700)
		if err != nil {
			rc.Close()
			return err
		}
		_, err = io.Copy(w, rc)
		w.Close()
		rc.Close()
		if err != nil {
			return err
		}
	}
	return nil
}

// askYesNo shows a Yes/No dialog and reports whether the user chose Yes.
func askYesNo(msg string) bool {
	text, _ := windows.UTF16PtrFromString(msg)
	title, _ := windows.UTF16PtrFromString("FortiProxy")
	const idYes = 6
	r, _ := windows.MessageBox(0, text, title, windows.MB_YESNO|windows.MB_ICONQUESTION)
	return r == idYes
}

// openURL opens a link in the user's default browser.
func openURL(u string) {
	cmd := exec.Command("rundll32", "url.dll,FileProtocolHandler", u)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	_ = cmd.Start()
}
