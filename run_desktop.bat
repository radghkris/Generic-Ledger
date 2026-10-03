@echo off
cd /d "%~dp0"

if exist "error_log.txt" del "error_log.txt"

where pythonw >nul 2>&1
if not errorlevel 1 (
    start "" pythonw desktop_app.py >"error_log.txt" 2>&1
    exit /b 0
)

where pyw >nul 2>&1
if not errorlevel 1 (
    start "" pyw desktop_app.py >"error_log.txt" 2>&1
    exit /b 0
)

echo Python wasn't found on this computer.
echo.
echo 1. Download Python from https://www.python.org/downloads/
echo 2. In the installer, tick "Add python.exe to PATH" on the first screen.
echo 3. Finish the install, then double-click this file again.
echo.
pause
