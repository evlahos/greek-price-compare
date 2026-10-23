@echo off
setlocal
cd /d "%~dp0"
echo ==========================================================
echo   Greek Price Compare - Build portable app
echo   Produces  dist\GreekPriceCompare\  that runs WITHOUT Python
echo   (run this once on a Windows PC that has Python 3.10+)
echo ==========================================================
echo.

set "PYEXE="
where py >nul 2>nul && set "PYEXE=py -3"
if not defined PYEXE ( where python >nul 2>nul && set "PYEXE=python" )
if not defined PYEXE (
  echo [ERROR] Python 3.10+ is required ON THIS BUILD MACHINE.
  echo Install from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^),
  echo then run build_exe.bat again.
  echo.
  pause
  exit /b 1
)
echo Using Python: %PYEXE%
%PYEXE% --version
echo.

echo [1/5] Creating build environment (.venv_build) ...
%PYEXE% -m venv .venv_build
if errorlevel 1 ( echo [ERROR] Could not create .venv_build & pause & exit /b 1 )
set "VPY=.venv_build\Scripts\python.exe"

echo [2/5] Installing build dependencies (playwright, pillow, pyinstaller) ...
"%VPY%" -m pip install --upgrade pip
"%VPY%" -m pip install playwright pillow pyinstaller
if errorlevel 1 ( echo [ERROR] pip install failed & pause & exit /b 1 )

echo [3/5] Downloading Chromium into local ms-playwright\ (~150 MB) ...
set "PLAYWRIGHT_BROWSERS_PATH=%cd%\ms-playwright"
"%VPY%" -m playwright install chromium
if errorlevel 1 ( echo [ERROR] chromium download failed & pause & exit /b 1 )

echo [4/5] Building the portable app (PyInstaller, bundling Chromium) ...
"%VPY%" -m PyInstaller --noconfirm --clean --name GreekPriceCompare ^
  --collect-all playwright ^
  --add-data "ms-playwright;ms-playwright" ^
  greek_price_app.py
if errorlevel 1 ( echo [ERROR] PyInstaller build failed & pause & exit /b 1 )

echo.
echo ==========================================================
echo   DONE.  Portable app is here:  dist\GreekPriceCompare\
echo.
echo   Copy the WHOLE folder  dist\GreekPriceCompare  to any
echo   Windows PC and run  GreekPriceCompare.exe  (no Python
echo   needed there). The folder is large (~300-400 MB) because
echo   it includes the Chromium browser.
echo ==========================================================
echo.
pause
