@echo off
setlocal

set "INSTALL_DIR=%APPDATA%\FortiProxy"
set "EXE=%~dp0FortiProxy.exe"

if not exist "%EXE%" (
    echo ERROR: FortiProxy.exe not found next to this script.
    pause
    exit /b 1
)

if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"

echo Installing FortiProxy...
copy /Y "%EXE%" "%INSTALL_DIR%\FortiProxy.exe" >nul 2>&1

if errorlevel 1 (
    echo ERROR: Failed to copy FortiProxy.exe to %INSTALL_DIR%
    pause
    exit /b 1
)

echo Launching FortiProxy...
start "" "%INSTALL_DIR%\FortiProxy.exe"

echo Done! FortiProxy is installed. Search for it in Windows Search to launch it next time.
timeout /t 3 >nul
