@echo off
setlocal
set "RUNTIME=%LOCALAPPDATA%\StreamSnip AI\runtime"
set "BOOTSTRAP=%~dp0bootstrap.ps1"

if not exist "%~dp0autoclip.py" goto :missing_app

if not exist "%RUNTIME%\Scripts\python.exe" (
  echo Installing the required StreamSnip AI runtime...
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%BOOTSTRAP%"
  if errorlevel 1 goto :failed
)

"%RUNTIME%\Scripts\python.exe" -c "import numpy, faster_whisper, streamlink" >nul 2>&1
if errorlevel 1 (
  echo Repairing the required StreamSnip AI runtime...
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%BOOTSTRAP%"
  if errorlevel 1 goto :failed
)

"%RUNTIME%\Scripts\python.exe" "%~dp0autoclip.py"
if errorlevel 1 goto :failed
exit /b 0

:failed
echo.
echo StreamSnip AI could not install its required runtime.
echo Check your internet connection and run this launcher again.
pause
exit /b 1

:missing_app
echo.
echo StreamSnip AI is missing an application file.
echo Please reinstall the latest StreamSnip AI installer.
pause
exit /b 2
