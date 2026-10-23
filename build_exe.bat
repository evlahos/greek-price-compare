@echo off
rem Builds a standalone Windows .exe (no Python needed on the target PC).
rem Run this ONCE on a Windows PC that already ran the installer (so .venv exists).
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [!] Run the installer first to create the .venv environment.
  pause ^& exit /b 1
)
set "PY=.venv\Scripts\python.exe"
"%PY%" -m pip install --upgrade pyinstaller || (pause ^& exit /b 1)
"%PY%" -m PyInstaller --noconfirm --onedir --windowed --name GreekPriceCompare --icon "app.ico" --add-data "static;static" --collect-all playwright --collect-all webview desktop.py
if errorlevel 1 (echo [!] Build failed. ^& pause ^& exit /b 1)
echo.
echo [OK] Done -^> dist\GreekPriceCompare\GreekPriceCompare.exe
echo Copy the whole  dist\GreekPriceCompare  folder to any Windows PC and run the exe.
pause
