@echo off
setlocal
set "RUNTIME=%LOCALAPPDATA%\StreamSnip AI\runtime"
"%RUNTIME%\Scripts\python.exe" "%~dp0autoclip.py"
if errorlevel 1 pause
