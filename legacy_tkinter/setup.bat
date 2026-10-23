@echo off
setlocal
cd /d "%~dp0"
echo ==========================================================
echo   Greek Price Compare - Setup
echo   Creates a local .venv and installs Playwright + Chromium
echo   (needed for the Skroutz and Public sources)
echo ==========================================================
echo.

REM --- locate Python ---
set "PYEXE="
where py >nul 2>nul && set "PYEXE=py -3"
if not defined PYEXE ( where python >nul 2>nul && set "PYEXE=python" )
if not defined PYEXE (
  echo [ERROR] Python was not found on this computer.
  echo.
  echo   1. Install Python 3.10 or newer from:
  echo        https://www.python.org/downloads/
  echo   2. During installation, tick "Add python.exe to PATH".
  echo   3. Run this setup.bat again.
  echo.
  pause
  exit /b 1
)
echo Using Python: %PYEXE%
%PYEXE% --version
echo.

echo [1/4] Creating virtual environment (.venv) ...
%PYEXE% -m venv .venv
if errorlevel 1 ( echo [ERROR] Could not create .venv & pause & exit /b 1 )

set "VPY=.venv\Scripts\python.exe"

echo [2/4] Upgrading pip ...
"%VPY%" -m pip install --upgrade pip

echo [3/4] Installing Playwright + Pillow ...
"%VPY%" -m pip install playwright pillow
if errorlevel 1 ( echo [ERROR] "pip install playwright pillow" failed & pause & exit /b 1 )

echo [4/4] Downloading the Chromium browser (~150 MB, one time) ...
"%VPY%" -m playwright install chromium
if errorlevel 1 ( echo [ERROR] "playwright install chromium" failed & pause & exit /b 1 )

echo.
echo ==========================================================
echo   Done!  Start the app now by double-clicking:  run_app.bat
echo ==========================================================
echo.
pause
