@echo off
cd /d "%~dp0"

if not exist ".venv" (
    echo Setting up the ledger for the first time...
    python -m venv .venv
)

call ".venv\Scripts\activate.bat"
pip install -r requirements.txt --quiet --disable-pip-version-check

if not exist "%USERPROFILE%\.streamlit" mkdir "%USERPROFILE%\.streamlit"
if not exist "%USERPROFILE%\.streamlit\credentials.toml" (
    echo [general] > "%USERPROFILE%\.streamlit\credentials.toml"
    echo email = "" >> "%USERPROFILE%\.streamlit\credentials.toml"
)

echo.
echo Starting the ledger... a browser tab will open shortly.
echo Close this window (or press Ctrl+C) to stop the app.
echo.
streamlit run app.py

pause
