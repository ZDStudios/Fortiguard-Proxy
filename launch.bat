@echo off
setlocal
set "DIR=%~dp0"

where python >nul 2>&1
if %errorlevel% neq 0 (
    echo Python not found. Download from https://python.org
    pause & exit /b 1
)

pip show customtkinter >nul 2>&1
if %errorlevel% neq 0 (
    echo Installing dependencies...
    pip install customtkinter pystray pillow -q --disable-pip-version-check
)

if not exist "%DIR%fortiproxy-client.exe" (
    echo [WARN] fortiproxy-client.exe not found.
    echo        Build it first:  cd client ^&^& .\build.ps1
    echo        The app will still open, but Connect won't work until it exists.
    echo.
)

python "%DIR%app\dashboard.py"
