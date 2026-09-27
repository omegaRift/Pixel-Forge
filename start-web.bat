@echo off
rem ------------------------------------------------------------------
rem  Pixel Forge (browser version) - opens the Streamlit app in your
rem  browser. Needs the desktop setup first; installs Streamlit on its
rem  first run. Close this window to stop the app.
rem ------------------------------------------------------------------
title Pixel Forge (web)
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [Pixel Forge] Run start.bat once first to set up Python.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\streamlit.exe" (
    echo [Pixel Forge] First web run: installing Streamlit...
    ".venv\Scripts\python.exe" -m pip install -q -r requirements-web.txt
    if errorlevel 1 (
        echo [Pixel Forge] Installing Streamlit failed - see the error above.
        pause
        exit /b 1
    )
)

echo [Pixel Forge] Starting... your browser will open at http://127.0.0.1:8501
echo [Pixel Forge] Close this window to stop the app.
".venv\Scripts\python.exe" -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501 --browser.gatherUsageStats false

rem Only reached if Streamlit exits with an error (e.g. port already in use).
if errorlevel 1 pause
