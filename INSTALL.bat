@echo off
rem ASCII-only launcher; logic + Greek messages live in setup.ps1 (UTF-8).
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
if errorlevel 1 (
    echo.
    echo Something went wrong. See the messages above.
    pause
)
