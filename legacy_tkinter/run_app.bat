@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" greek_price_app.py
    if errorlevel 1 pause
    exit /b
)
where python >nul 2>nul
if %errorlevel%==0 (
    python greek_price_app.py
    if errorlevel 1 pause
    exit /b
)
echo ERROR: Python was not found.
echo Install Python 3.10 or newer from https://www.python.org/downloads/
echo During installation, enable "Add python.exe to PATH".
pause
