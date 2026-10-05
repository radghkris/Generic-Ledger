@echo off
rem One-file installer: download just this file, double-click it. It fetches the app,
rem installs Python if needed, puts a "Generic Ledger" shortcut on the Desktop, and starts it.
echo Setting up Generic Ledger - this takes a minute...
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol='Tls12'; $f=Join-Path $env:TEMP 'ledger_setup.ps1'; Invoke-WebRequest -UseBasicParsing 'https://raw.githubusercontent.com/radghkris/Generic-Ledger/main/tools/setup.ps1' -OutFile $f; & $f"
if errorlevel 1 pause
