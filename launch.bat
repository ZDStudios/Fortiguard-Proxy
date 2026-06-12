@echo off
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo Python not found. Download from https://python.org
    pause & exit /b 1
)
pip show customtkinter >nul 2>&1
if %errorlevel% neq 0 (
    echo Installing customtkinter...
    pip install customtkinter -q --disable-pip-version-check
)
python "%~dp0app\dashboard.py"
