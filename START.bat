@echo off
chcp 65001 >nul
title PriceScout
cd /d "%~dp0"

echo.
echo ============================================================
echo   PriceScout - price monitoring for construction materials
echo ============================================================
echo.

REM ---- Check that Python is installed ----
where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python was not found on this computer.
  echo.
  echo   1. Install Python 3.10 or newer from:
  echo      https://www.python.org/downloads/
  echo   2. During installation, TICK the checkbox
  echo      "Add python.exe to PATH".
  echo   3. Run START.bat again.
  echo.
  pause
  exit /b 1
)

REM ---- Check Python version (need 3.10 or newer) ----
python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" 2>nul
if errorlevel 1 (
  echo [ERROR] Python 3.10 or newer is required.
  echo Installed version:
  python --version
  echo Please update Python: https://www.python.org/downloads/
  echo.
  pause
  exit /b 1
)

REM ---- Create the virtual environment (first run only) ----
if not exist ".venv\Scripts\python.exe" (
  echo [Setup 1/2] Creating virtual environment...
  python -m venv .venv
  if errorlevel 1 (
    echo [ERROR] Could not create the virtual environment.
    pause
    exit /b 1
  )
)

call ".venv\Scripts\activate.bat"

REM ---- Install dependencies (first run only) ----
if not exist ".venv\.setup_done" (
  echo [Setup 2/2] Installing components.
  echo This happens only once and takes a few minutes - please wait...
  echo.
  python -m pip install --upgrade pip
  pip install -r requirements.txt
  if errorlevel 1 (
    echo.
    echo [ERROR] Could not install dependencies.
    echo Check your internet connection and run START.bat again.
    pause
    exit /b 1
  )
  echo.
  echo Installing the browser used for price scraping...
  scrapling install
  if errorlevel 1 python -m playwright install chromium
  type nul > ".venv\.setup_done"
  echo.
  echo Setup complete.
  echo.
)

REM ---- Start the app ----
echo Starting PriceScout...
echo.
echo   Address:  http://localhost:5000
echo   The browser should open automatically in a few seconds.
echo   To stop the program, just close this window.
echo.

start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 5; Start-Process 'http://localhost:5000'"

python app.py

echo.
echo PriceScout has stopped. You can close this window.
pause
