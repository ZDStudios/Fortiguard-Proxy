@echo off
setlocal EnableDelayedExpansion
set "DIR=%~dp0"
title FortiProxy

:: ── Auto-elevate to admin ──────────────────────────────────────────────────
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [FortiProxy] Requesting admin rights...
    powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo.
echo  ===================================
echo   FortiProxy Connector
echo  ===================================
echo.

:: ── Check Node is installed ────────────────────────────────────────────────
where node >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Node.js is not installed.
    echo         Download it from https://nodejs.org then re-run this script.
    echo.
    pause
    exit /b 1
)

for /f "tokens=*" %%v in ('node -v') do set NODEVER=%%v
echo [OK] Node.js %NODEVER% found

:: ── Install ws package if needed ───────────────────────────────────────────
if not exist "%DIR%node_modules\ws\package.json" (
    echo [....] Installing dependencies ^(ws package^)...
    pushd "%DIR%"
    npm install
    if %errorlevel% neq 0 (
        echo.
        echo [ERROR] npm install failed. Check the output above.
        popd
        pause
        exit /b 1
    )
    popd
    echo [OK] Dependencies installed.
) else (
    echo [OK] Dependencies already installed.
)

:: ── Enable system proxy ────────────────────────────────────────────────────
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyEnable /t REG_DWORD /d 1 /f >nul
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyServer /t REG_SZ /d "127.0.0.1:8080" /f >nul
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyOverride /t REG_SZ /d "localhost;127.*;10.*;192.168.*;*.local;<local>" /f >nul
echo [OK] System proxy set to 127.0.0.1:8080

echo.
echo [FortiProxy] Tunnel connecting to fortiguard-proxy.onrender.com...
echo [FortiProxy] Close this window at any time to disconnect.
echo.

:: ── Start tunnel (window stays open until you close it) ───────────────────
node "%DIR%client.js"

:: ── If node exits for any reason, show why before closing ─────────────────
echo.
if %errorlevel% neq 0 (
    echo [ERROR] client.js exited with code %errorlevel%
    echo         Check the output above for details.
) else (
    echo [FortiProxy] Tunnel closed normally.
)

:: ── Disable proxy on exit ──────────────────────────────────────────────────
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyEnable /t REG_DWORD /d 0 /f >nul
echo [OK] System proxy disabled.
echo.
pause
