@echo off
rem Opens the app in your default browser instead of a window.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" -Browser
if errorlevel 1 pause
