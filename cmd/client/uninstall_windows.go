package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"syscall"
	"time"

	"golang.org/x/sys/windows"
)

// uninstall removes every part of FortiProxy: the installed program, its Start
// Menu shortcut, and all of its data (settings, logs, webview cache). It first
// confirms with the user, then turns the tunnel off and restores the network so
// nothing is left behind, and finally hands off to a small self-deleting batch
// that removes the folders once this process has exited.
func uninstall(engine *Engine) {
	defer func() { _ = recover() }()

	const warning = "This will uninstall every part of FortiProxy — the app, " +
		"its settings, logs and Start Menu shortcut will all be removed.\n\n" +
		"Are you sure you want to do this?"
	if !askYesNo(warning) {
		return
	}

	// Turn the proxy off and clear any leftover network state before we go, so a
	// half-removed install can never strand the machine's networking.
	engine.Stop("")
	repairNetwork(engine.dir)
	engine.Logs.Add("warn", "Uninstalling FortiProxy at the user's request")

	appData := os.Getenv("APPDATA")
	installDir := filepath.Join(appData, "FortiProxy")
	dataDir := engine.dir // %LOCALAPPDATA%\FortiProxy
	shortcut := filepath.Join(appData, `Microsoft\Windows\Start Menu\Programs\FortiProxy.lnk`)

	// A detached batch does the deletion: it waits for this process (and the
	// crash watchdog, which is the same exe) to exit, removes everything, then
	// deletes itself. %~f0 is the batch's own path.
	script := "@echo off\r\n" +
		"taskkill /IM FortiProxy.exe /F >nul 2>&1\r\n" +
		"timeout /t 2 /nobreak >nul\r\n" +
		fmt.Sprintf("rmdir /s /q \"%s\" >nul 2>&1\r\n", installDir) +
		fmt.Sprintf("rmdir /s /q \"%s\" >nul 2>&1\r\n", dataDir) +
		fmt.Sprintf("del /f /q \"%s\" >nul 2>&1\r\n", shortcut) +
		"del /f /q \"%~f0\" >nul 2>&1\r\n"

	bat := filepath.Join(os.TempDir(), "FortiProxy_uninstall.bat")
	if err := os.WriteFile(bat, []byte(script), 0o700); err != nil {
		engine.Logs.Add("error", "Uninstall failed: %v", err)
		alert("Couldn't start the uninstaller:\n" + err.Error())
		return
	}

	cmd := exec.Command("cmd", "/c", bat)
	cmd.Dir = os.TempDir() // never hold a FortiProxy folder open
	cmd.SysProcAttr = &syscall.SysProcAttr{
		HideWindow:    true,
		CreationFlags: windows.CREATE_NO_WINDOW | windows.CREATE_NEW_PROCESS_GROUP | windows.CREATE_BREAKAWAY_FROM_JOB,
	}
	if err := cmd.Start(); err != nil {
		engine.Logs.Add("error", "Uninstall failed: %v", err)
		alert("Couldn't start the uninstaller:\n" + err.Error())
		return
	}
	cmd.Process.Release()
	time.Sleep(400 * time.Millisecond)
	os.Exit(0)
}
