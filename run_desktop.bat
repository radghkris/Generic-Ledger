@echo off
cd /d "%~dp0"

if exist "error_log.txt" del "error_log.txt"

rem Copies made by Install-Ledger.bat (no .git folder) quietly pick up new versions. Skipped if offline.
if not exist ".git" if exist "tools\setup.ps1" powershell -NoProfile -ExecutionPolicy Bypass -File "tools\setup.ps1" -Update >nul 2>&1

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

if defined LEDGER_RETRIED (
    echo Python still isn't available. Close this window and double-click the shortcut again.
    pause
    exit /b 1
)
echo Python wasn't found on this computer - installing it now.
powershell -NoProfile -ExecutionPolicy Bypass -File "tools\setup.ps1" -NoLaunch
if errorlevel 1 exit /b 1
for /d %%d in ("%LOCALAPPDATA%\Programs\Python\Python3*") do set "PATH=%%d;%PATH%"
set LEDGER_RETRIED=1
call "%~f0"
