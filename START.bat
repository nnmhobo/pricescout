@echo off
chcp 65001 >nul
title PriceScout
cd /d "%~dp0"

REM ============================================================
REM  PriceScout launcher.
REM  All setup and startup happens in a GUI window (setup_gui.py).
REM  This console appears only if Python itself is missing.
REM ============================================================

where pythonw >nul 2>nul
if not errorlevel 1 (
  start "" pythonw setup_gui.py
  exit /b 0
)

where python >nul 2>nul
if not errorlevel 1 (
  REM pythonw not on PATH — fall back to python (a console may flash).
  start "" /min python setup_gui.py
  exit /b 0
)

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
