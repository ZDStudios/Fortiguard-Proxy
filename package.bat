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

:: ── Read the version from docs\version.txt (e.g. V26) ────────────────────────
set "VER="
if exist "docs\version.txt" set /p VER=<docs\version.txt
if "%VER%"=="" set "VER=V26"
echo  Version: %VER%
echo.

where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Download from https://python.org
    pause & exit /b 1
)

where go >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARN] Go not found. If fortiproxy-client.exe is missing, install Go:
    echo        winget install GoLang.Go
    echo.
)

:: ── Make sure the required files exist ───────────────────────────────────────
if not exist "secrets.env" (
    echo [ERROR] secrets.env not found. Copy secrets.env.example to secrets.env
    echo         and set your PROXY_TOKEN, then run this again.
    pause & exit /b 1
)
if not exist "install.bat" (
    echo [ERROR] install.bat not found next to this script.
    pause & exit /b 1
)

:: ── Install build dependencies ───────────────────────────────────────────────
echo [....] Installing build dependencies...
pip install pyinstaller customtkinter pystray pillow -q --disable-pip-version-check
echo [OK]   Dependencies ready
echo.

:: ── Build FortiProxy.exe (this also builds the Go tunnel client) ─────────────
echo [....] Building FortiProxy.exe - this takes 30-60 seconds...
echo.
python "app\build_exe.py"
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

:: ── Zip FortiProxy.exe + install.bat into FortiProxy-<VER>.zip ───────────────
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
echo  To publish it to GitHub Releases instead, run:  python release.py %VER%
echo.
pause
