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
	"syscall"
	"time"

	"golang.org/x/sys/windows"
)

// appVersion is baked in at build time by build.ps1 from docs/version.txt
// (e.g. "V27"). It is what the updater compares against the published version.
var appVersion = "dev"

const updateRepo = "ZDStudios/Fortiguard-Proxy"

// Where the auto-updater looks. The version file and the matching release zip
// both live in the repo root on the main branch, served raw by GitHub. This is
// the same contract the older installs use, so every version can update to the
// next one.
func versionURL() string {
	return "https://raw.githubusercontent.com/" + updateRepo + "/main/docs/version.txt"
}

func zipURL(version string) string {
	return "https://raw.githubusercontent.com/" + updateRepo + "/main/FortiProxy-" + version + ".zip"
}

// versionNum turns "V27" (or "v27", " 27 ") into 27 so versions can be compared.
func versionNum(v string) int {
	v = strings.TrimSpace(v)
	v = strings.TrimPrefix(strings.ToUpper(v), "V")
	n, _ := strconv.Atoi(strings.TrimSpace(v))
	return n
}

// checkForUpdate looks for a newer published version and, if the user agrees,
// downloads it and hands off to install.bat. It never touches anything unless
// the published version is strictly newer, so a normal launch does nothing.
func checkForUpdate(engine *Engine) {
	defer func() { _ = recover() }()
	logs := engine.Logs
	client := &http.Client{Timeout: 15 * time.Second}

	resp, err := client.Get(versionURL())
	if err != nil {
		logs.Add("info", "Update check skipped: %v", err)
		return
	}
	b, _ := io.ReadAll(io.LimitReader(resp.Body, 64))
	resp.Body.Close()
	latest := strings.TrimSpace(string(b))
	if latest == "" || versionNum(latest) <= versionNum(appVersion) {
		return
	}

	logs.Add("warn", "A new version is available: %s (you have %s)", latest, appVersion)
	msg := fmt.Sprintf("A new version of FortiProxy (%s) is available.\n\nUpdate now? FortiProxy will close briefly and reopen.", latest)
	if !askYesNo(msg) {
		return
	}
	if err := downloadAndInstall(engine, client, latest); err != nil {
		logs.Add("error", "Update failed: %v", err)
		alert("The update couldn't be installed:\n" + err.Error())
	}
}

func downloadAndInstall(engine *Engine, client *http.Client, latest string) error {
	engine.Logs.Add("info", "Downloading FortiProxy %s...", latest)
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
