@echo off
:: ============================================================
::  FortiProxy Connector
::  Edit PROXY_HOST and PROXY_TOKEN before first use.
:: ============================================================

set PROXY_HOST=fortiguard-proxy.onrender.com
set PROXY_PORT=443
set PROXY_TOKEN=YOUR_SECRET_TOKEN

:: Build the proxy URL with auth credentials baked in
set PROXY_URL=http://proxy:%PROXY_TOKEN%@%PROXY_HOST%:%PROXY_PORT%

echo.
echo [FortiProxy] Setting system proxy to: %PROXY_HOST%:%PROXY_PORT%
echo.

:: Enable proxy for the current user
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyEnable /t REG_DWORD /d 1 /f >nul
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyServer /t REG_SZ /d "%PROXY_HOST%:%PROXY_PORT%" /f >nul
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyOverride /t REG_SZ /d "localhost;127.*;10.*;192.168.*;*.local;<local>" /f >nul

:: Store credentials in Windows Credential Manager so browsers use them
cmdkey /add:%PROXY_HOST% /user:proxy /pass:%PROXY_TOKEN% >nul

echo [FortiProxy] System proxy ENABLED.
echo [FortiProxy] Bypassing: localhost, 127.x, 10.x, 192.168.x, *.local
echo.
echo Press any key to DISABLE the proxy and exit...
pause >nul

:: Disable on exit
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyEnable /t REG_DWORD /d 0 /f >nul
cmdkey /delete:%PROXY_HOST% >nul

echo [FortiProxy] System proxy DISABLED.
echo.
