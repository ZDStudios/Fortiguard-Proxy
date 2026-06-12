@echo off
setlocal EnableDelayedExpansion
set "DIR=%~dp0"
title FortiProxy

:: ── Auto-elevate to admin ──────────────────────────────────────────────────
net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo.
echo  ===================================
echo   FortiProxy Connector
echo  ===================================
echo.

:: ── Check Node ────────────────────────────────────────────────────────────
where node >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Node.js not found. Download from https://nodejs.org
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('node -v') do echo [OK] Node.js %%v

:: ── Install ws if needed ──────────────────────────────────────────────────
if not exist "!DIR!node_modules\ws\package.json" (
    echo [....] Installing dependencies...
    pushd "!DIR!"
    npm install
    if !errorlevel! neq 0 (
        echo [ERROR] npm install failed - see output above
        popd
        pause
        exit /b 1
    )
    popd
    echo [OK] Dependencies installed
) else (
    echo [OK] Dependencies already installed
)

:: ── Build PAC file URL ────────────────────────────────────────────────────
set "PACPATH=!DIR!proxy.pac"
set "PACPATH=!PACPATH:\=/!"
set "PACURL=file:///!PACPATH!"

:: ── Enable proxy via PAC (DIRECT fallback means internet works even if
::    this window is force-closed before cleanup runs) ──────────────────────
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v AutoConfigURL /t REG_SZ    /d "!PACURL!" /f >nul
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyEnable   /t REG_DWORD /d 1          /f >nul
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyServer /f >nul 2>&1

echo [OK] Proxy enabled
echo.
echo [FortiProxy] Starting tunnel to fortiguard-proxy.onrender.com...
echo [FortiProxy] Close this window to disconnect.
echo [FortiProxy] If internet breaks after closing, run disable-proxy.bat
echo.

:: ── Start tunnel (blocks until node exits) ───────────────────────────────
node "!DIR!client.js"
set EXITCODE=!errorlevel!

:: ── Cleanup (runs on Ctrl+C or crash — not on X-close, but PAC DIRECT
::    fallback keeps internet working regardless) ───────────────────────────
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyEnable /t REG_DWORD /d 0 /f >nul
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v AutoConfigURL /f >nul 2>&1

echo.
if !EXITCODE! neq 0 (
    echo [ERROR] Tunnel exited with code !EXITCODE! - check output above
) else (
    echo [FortiProxy] Disconnected cleanly.
)
echo [FortiProxy] Proxy disabled.
echo.
pause
