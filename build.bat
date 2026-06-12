@echo off
setlocal
set "DIR=%~dp0"
title FortiProxy - Build EXE

echo.
echo  ===================================
echo   FortiProxy - EXE Builder
echo  ===================================
echo.

:: Check Python
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Download from https://python.org
    pause & exit /b 1
)

:: Install deps
echo [....] Installing build dependencies...
pip install pyinstaller customtkinter -q --disable-pip-version-check
echo [OK]   Dependencies ready

:: Clean old build
if exist "%DIR%dist\FortiProxy.exe" del /f /q "%DIR%dist\FortiProxy.exe"
if exist "%DIR%build"               rmdir /s /q "%DIR%build"
if exist "%DIR%FortiProxy.spec"     del /f /q "%DIR%FortiProxy.spec"

:: Build (single line - avoids ^ continuation issues)
echo [....] Compiling - this takes 30-60 seconds...
echo.

pyinstaller --onefile --windowed --collect-all customtkinter --name "FortiProxy" --distpath "%DIR%dist" --workpath "%DIR%build" --specpath "%DIR%" "%DIR%dashboard.py"

echo.
if not exist "%DIR%dist\FortiProxy.exe" (
    echo [ERROR] Build failed - check output above
    pause & exit /b 1
)

echo [OK]   Build complete!
echo.
echo  EXE is at:
echo    %DIR%dist\FortiProxy.exe
echo.
echo  Copy these into the same folder as FortiProxy.exe:
echo    client.js
echo    proxy.pac
echo    package.json
echo  Then run: npm install
echo.
pause
