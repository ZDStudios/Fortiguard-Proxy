@echo off
setlocal enabledelayedexpansion
title FortiProxy - Publish V25 to GitHub

:: Publishes this project to GitHub as a new commit on top of the existing
:: history (no force-push). It also commits FortiProxy-<ver>.zip to the repo
:: root, which is REQUIRED for the in-app auto-updater: existing installs
:: download the new version from
::   https://raw.githubusercontent.com/ZDStudios/Fortiguard-Proxy/main/FortiProxy-<ver>.zip
::
:: Run package.bat FIRST so the zip exists, then run this.

set "SRC=%~dp0"
set "WORK=%TEMP%\fortiproxy-publish"
set "REPO=https://github.com/ZDStudios/Fortiguard-Proxy.git"

where git >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Git not found. Install it from https://git-scm.com
    pause & exit /b 1
)

:: Version label from docs\version.txt (e.g. V25)
set "VER="
if exist "%SRC%docs\version.txt" set /p VER=<"%SRC%docs\version.txt"
if "%VER%"=="" set "VER=V25"
set "ZIP=FortiProxy-%VER%.zip"

:: The release zip MUST exist, or existing installs can't auto-update.
if not exist "%SRC%%ZIP%" (
    echo [ERROR] %ZIP% not found in this folder.
    echo         Build it first by running:  package.bat
    echo         The auto-updater downloads this zip, so it must be published.
    pause & exit /b 1
)

echo.
echo  Publishing %VER%  (code + %ZIP% for the auto-updater)
echo.

:: Fresh clone of the real repo (keeps all existing history and old zips)
if exist "%WORK%" rmdir /s /q "%WORK%"
git clone "%REPO%" "%WORK%"
if %errorlevel% neq 0 ( echo [ERROR] Clone failed. & pause & exit /b 1 )

:: Mirror the code into the clone. Exclude .git, build junk, secrets, the bare
:: exes, and ALL zips -- excluding zips means the repo's existing release zips
:: are preserved (not purged), and we add this version's zip explicitly below.
robocopy "%SRC%." "%WORK%." /MIR /XD .git __pycache__ "%SRC%app\build" ^
    /XF secrets.env fortiproxy-client.exe FortiProxy.exe FortiProxy-*.zip *.pyc >nul
if %errorlevel% geq 8 ( echo [ERROR] Copy failed. & pause & exit /b 1 )

:: Put THIS version's zip in the repo root for the auto-updater.
copy /Y "%SRC%%ZIP%" "%WORK%\%ZIP%" >nul

cd /d "%WORK%"
git add -A

git diff --cached --quiet
if %errorlevel% equ 0 (
    echo [INFO] No changes versus GitHub — nothing to publish.
    pause & exit /b 0
)

git commit -m "%VER%: hosted proxy backend, Go tunnel client, redesigned app, self-healing" ^
           -m "Backend moves to proxy.zdstudios.network; Go yamux tunnel client (HTTP+SOCKS5, 4 links); redesigned desktop app; crash recovery (panic isolation, guardian process, clear-proxy on exit, app poll, launch heal); GitHub Pages panel removed. Release zip committed so existing installs auto-update." ^
           -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
if %errorlevel% neq 0 ( echo [ERROR] Commit failed. & pause & exit /b 1 )

echo.
echo  Pushing to GitHub (you may be asked to sign in)...
git push
if %errorlevel% neq 0 ( echo [ERROR] Push failed. Sign in and retry 'git push' from %WORK% & pause & exit /b 1 )

echo.
echo  ===================================
echo   Done. %VER% is live on GitHub.
echo   Existing installs will auto-update on next launch.
echo  ===================================
echo.
pause
