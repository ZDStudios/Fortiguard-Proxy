@echo off
setlocal enabledelayedexpansion
set "DIR=%~dp0"
cd /d "%DIR%"
title FortiProxy - Package Release

echo.
echo  ===================================
echo   FortiProxy - Release Packager
echo  ===================================
echo.

:: -- Read the version from docs\version.txt (e.g. V27) -----------------------
set "VER="
if exist "docs\version.txt" set /p VER=<docs\version.txt
if "%VER%"=="" set "VER=V27"
echo  Version: %VER%
echo.

where go >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Go not found. Install it:  winget install GoLang.Go
    pause & exit /b 1
)

if not exist "secrets.env" (
    echo [ERROR] secrets.env not found. Copy secrets.env.example to secrets.env
    echo         and set your PROXY_TOKEN, then run this again.
    pause & exit /b 1
)
if not exist "install.bat" (
    echo [ERROR] install.bat not found next to this script.
    pause & exit /b 1
)

:: -- Build FortiProxy.exe (Go TUN client + webview UI, with admin manifest) --
echo [....] Building FortiProxy.exe - this can take a minute...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File ".\build.ps1"
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Build failed - check the output above.
    pause & exit /b 1
)
if not exist "FortiProxy.exe" (
    echo [ERROR] FortiProxy.exe was not produced.
    pause & exit /b 1
)
echo [OK]   FortiProxy.exe built
echo.

:: -- Zip FortiProxy.exe + install.bat into FortiProxy-<VER>.zip --------------
set "ZIP=FortiProxy-%VER%.zip"
if exist "%ZIP%" del /f /q "%ZIP%"
echo [....] Creating %ZIP% ...
powershell -NoProfile -Command "Compress-Archive -Path 'FortiProxy.exe','install.bat' -DestinationPath '%ZIP%' -Force"
if %errorlevel% neq 0 (
    echo [ERROR] Could not create the zip.
    pause & exit /b 1
)

echo.
echo  ===================================
echo   Done:  %ZIP%
echo   Contents: FortiProxy.exe + install.bat
echo  ===================================
echo.
echo  To publish it to GitHub (code + zip for the auto-updater), run:  publish.bat
echo.
pause
