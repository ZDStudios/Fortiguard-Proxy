@echo off
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyEnable /t REG_DWORD /d 0 /f >nul
echo [FortiProxy] Proxy DISABLED. Your internet is back to normal.
timeout /t 2 >nul
