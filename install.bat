@echo off
setlocal

set "INSTALL_DIR=%APPDATA%\FortiProxy"
set "EXE=%~dp0FortiProxy.exe"

:: Capture temp dir path (strip trailing backslash for PowerShell)
set "TMP_DIR=%~dp0"
if "%TMP_DIR:~-1%"=="\" set "TMP_DIR=%TMP_DIR:~0,-1%"

if not exist "%EXE%" (
    echo ERROR: FortiProxy.exe not found next to this script.
    pause
    exit /b 1
)

if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"

:: Signal FortiProxy to quit gracefully (cleans up tray icon properly)
echo Stopping FortiProxy...
echo quit > "%APPDATA%\FortiProxy\.quit_signal"
timeout /t 4 /nobreak >nul

:: Kill any remaining FortiProxy and node processes
taskkill /IM node.exe /F >nul 2>&1
taskkill /IM FortiProxy.exe /F >nul 2>&1
timeout /t 2 /nobreak >nul

echo Installing FortiProxy...
copy /Y "%EXE%" "%INSTALL_DIR%\FortiProxy.exe" >nul 2>&1

if errorlevel 1 (
    echo ERROR: Failed to copy FortiProxy.exe to %INSTALL_DIR%
    pause
    exit /b 1
)

:: Remove "downloaded from internet" mark so Windows doesn't restrict it
powershell -WindowStyle Hidden -Command "Unblock-File -Path '%INSTALL_DIR%\FortiProxy.exe'" >nul 2>&1

echo Launching FortiProxy...
start "" "%INSTALL_DIR%\FortiProxy.exe"

echo Done!

:: Schedule deletion of this temp folder 8 seconds after we exit
:: (can't delete it while bat is running from inside it)
start /b powershell -WindowStyle Hidden -Command "$p='%TMP_DIR%'; Start-Sleep 8; if(Test-Path $p){Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction SilentlyContinue}"

timeout /t 2 /nobreak >nul
