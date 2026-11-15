@echo off
setlocal

set "INSTALL_DIR=%APPDATA%\FortiProxy"
set "EXE=%~dp0FortiProxy.exe"
set "STAGE_EXE=%TEMP%\FortiProxy_update_new.exe"

:: Folder this script lives in (the extracted download) — no trailing backslash.
set "SRC_DIR=%~dp0"
if "%SRC_DIR:~-1%"=="\" set "SRC_DIR=%SRC_DIR:~0,-1%"

if not exist "%EXE%" (
    echo ERROR: FortiProxy.exe not found next to this script.
    pause
    exit /b 1
)

if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"

:: Stage the exe to %TEMP% first, so the installed copy never depends on this folder.
echo Staging...
copy /Y "%EXE%" "%STAGE_EXE%" >nul 2>&1
if errorlevel 1 (
    echo ERROR: Could not stage FortiProxy.exe to a temp location.
    pause
    exit /b 1
)

:: Stop any running FortiProxy (the app and its crash watchdog are both this exe)
:: so nothing stays locked.
echo Stopping any running FortiProxy...
taskkill /IM FortiProxy.exe /F >nul 2>&1
timeout /t 2 /nobreak >nul

echo Installing to "%INSTALL_DIR%" ...
copy /Y "%STAGE_EXE%" "%INSTALL_DIR%\FortiProxy.exe" >nul 2>&1
if errorlevel 1 (
    echo ERROR: Failed to copy FortiProxy.exe to %INSTALL_DIR%
    pause
    exit /b 1
)
del /F /Q "%STAGE_EXE%" >nul 2>&1

:: Remove the "downloaded from the internet" mark so Windows doesn't restrict it.
powershell -NoProfile -WindowStyle Hidden -Command "Unblock-File -Path '%INSTALL_DIR%\FortiProxy.exe'" >nul 2>&1

:: Create a Start Menu shortcut so FortiProxy shows up in Windows Search.
set "SM=%APPDATA%\Microsoft\Windows\Start Menu\Programs"
powershell -NoProfile -WindowStyle Hidden -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%SM%\FortiProxy.lnk'); $s.TargetPath='%INSTALL_DIR%\FortiProxy.exe'; $s.WorkingDirectory='%INSTALL_DIR%'; $s.Save()" >nul 2>&1

:: Launch the INSTALLED copy. /D sets its working directory to %INSTALL_DIR% so it
:: does NOT hold this download folder open (a process's working directory can't be
:: deleted) — that was what left the folder "in use". FortiProxy asks for admin
:: (it needs it to create the network adapter), so Windows may show a prompt.
echo Launching FortiProxy...
start "" /D "%INSTALL_DIR%" "%INSTALL_DIR%\FortiProxy.exe"

echo.
echo Done! FortiProxy is installed and running. You can close this window —
echo this downloaded folder will delete itself automatically.

:: Detached, self-healing cleanup: survives this window closing, waits for cmd to
:: release the folder, kills ONLY a copy still running FROM this download folder
:: (never the installed one in %%APPDATA%%), then retries the delete until gone.
start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep 3; for($i=0; $i -lt 20; $i++){ Get-Process FortiProxy -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $_.Path -like '%SRC_DIR%\*' } | Stop-Process -Force -ErrorAction SilentlyContinue; Remove-Item -LiteralPath '%SRC_DIR%' -Recurse -Force -ErrorAction SilentlyContinue; if(-not (Test-Path -LiteralPath '%SRC_DIR%')){ break }; Start-Sleep 1 }"

exit
