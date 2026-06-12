@echo off
setlocal
set "DIR=%~dp0"

:: ── Check Node is installed ────────────────────────────────────────────────
where node >nul 2>&1
if errorlevel 1 (
    echo [FortiProxy] ERROR: Node.js is not installed.
    echo             Download it from https://nodejs.org and re-run this script.
    pause
    exit /b 1
)

:: ── Install ws package if needed ───────────────────────────────────────────
if not exist "%DIR%node_modules\ws" (
    echo [FortiProxy] Installing dependencies...
    pushd "%DIR%"
    npm install --silent
    popd
)

:: ── Enable system proxy (no admin needed for current user) ─────────────────
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyEnable /t REG_DWORD /d 1 /f >nul
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyServer /t REG_SZ /d "127.0.0.1:8080" /f >nul
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyOverride /t REG_SZ /d "localhost;127.*;10.*;192.168.*;*.local;<local>" /f >nul

echo.
echo [FortiProxy] System proxy set to 127.0.0.1:8080
echo [FortiProxy] Starting tunnel to fortiguard-proxy.onrender.com...
echo [FortiProxy] Close this window to disconnect.
echo.

:: ── Start local proxy (blocks until window is closed) ──────────────────────
node "%DIR%client.js"

:: ── Cleanup on exit ────────────────────────────────────────────────────────
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyEnable /t REG_DWORD /d 0 /f >nul
echo.
echo [FortiProxy] Proxy disabled. Goodbye.
