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

:: ── Hand off to PowerShell which handles cleanup even on window close ──────
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$dir = '%DIR:\=\\%';" ^
    "function Disable-Proxy {" ^
    "    Set-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' ProxyEnable 0;" ^
    "    Write-Host ''; Write-Host '[FortiProxy] Proxy DISABLED. Internet restored.'" ^
    "};" ^
    "try {" ^
    "    $node = Get-Command node -ErrorAction Stop;" ^
    "    if (-not (Test-Path \"${dir}node_modules\ws\")) {" ^
    "        Write-Host '[....] Installing dependencies...';" ^
    "        Push-Location $dir;" ^
    "        npm install;" ^
    "        Pop-Location;" ^
    "        if ($LASTEXITCODE -ne 0) { throw 'npm install failed' }" ^
    "    };" ^
    "    Set-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' ProxyEnable 1;" ^
    "    Set-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' ProxyServer '127.0.0.1:8080';" ^
    "    Set-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' ProxyOverride 'localhost;127.*;10.*;192.168.*;*.local;<local>';" ^
    "    Write-Host '[OK] System proxy set to 127.0.0.1:8080';" ^
    "    Write-Host '[FortiProxy] Starting tunnel... Close this window to disconnect.';" ^
    "    Write-Host '';" ^
    "    & node \"${dir}client.js\"" ^
    "} catch {" ^
    "    Write-Host \"[ERROR] $_\"" ^
    "} finally {" ^
    "    Disable-Proxy;" ^
    "    Write-Host 'Press Enter to close...';" ^
    "    Read-Host" ^
    "}"
