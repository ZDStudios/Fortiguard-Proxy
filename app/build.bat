@echo off
setlocal
set "DIR=%~dp0"
title FortiProxy - Build EXE

echo.
echo  ===================================
echo   FortiProxy - EXE Builder
echo  ===================================
echo.

where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Download from https://python.org
    pause & exit /b 1
)

echo [....] Installing build dependencies...
pip install pyinstaller customtkinter -q --disable-pip-version-check
echo [OK]   Dependencies ready
echo.
echo [....] Compiling - this takes 30-60 seconds...
echo.

python "%DIR%build_exe.py"

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Build failed - check output above
    pause & exit /b 1
)

echo.
echo [OK]   FortiProxy.exe is ready in the project root folder.
echo.
pause
