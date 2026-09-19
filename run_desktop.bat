@echo off
cd /d "%~dp0"

if exist "error_log.txt" del "error_log.txt"
start "" pythonw desktop_app.py >"error_log.txt" 2>&1
