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

:: Move into the project folder so all paths are relative (avoids trailing-backslash quoting bug)
pushd "%DIR%"

:: Clean previous build
if exist "build"           rmdir /s /q "build"
if exist "FortiProxy.spec" del /f /q "FortiProxy.spec"
if exist "FortiProxy.exe"  del /f /q "FortiProxy.exe"

echo [....] Compiling - this takes 30-60 seconds...
echo.

pyinstaller --onefile --windowed --collect-all customtkinter --name "FortiProxy" --distpath "." --workpath "build" --specpath "." "dashboard.py"

set RESULT=%errorlevel%

:: Clean up build leftovers
if exist "build"           rmdir /s /q "build"
if exist "FortiProxy.spec" del /f /q "FortiProxy.spec"

popd

echo.
if %RESULT% neq 0 (
    echo [ERROR] Build failed - check output above
    pause & exit /b 1
)

if not exist "%DIR%FortiProxy.exe" (
    echo [ERROR] EXE not found after build
    pause & exit /b 1
)

echo [OK]   Build complete!
echo.
echo  FortiProxy.exe is ready in:
echo    %DIR%
echo.
pause
