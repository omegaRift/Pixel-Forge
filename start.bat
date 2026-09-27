@echo off
rem ------------------------------------------------------------------
rem  Pixel Forge launcher - double-click to open the desktop app.
rem  First run creates a local .venv and installs Pillow; after that
rem  the app window opens straight away and this console closes.
rem  Tip: drag an image onto this file to open it directly.
rem ------------------------------------------------------------------
title Pixel Forge
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
    echo [Pixel Forge] First run: setting up a local Python environment...
    where python >nul 2>nul
    if errorlevel 1 (
        echo [Pixel Forge] Python was not found. Install Python 3.10+ from python.org and tick "Add to PATH".
        pause
        exit /b 1
    )
    python -m venv .venv
    if errorlevel 1 (
        echo [Pixel Forge] Could not create the virtual environment.
        pause
        exit /b 1
    )
    ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
    if errorlevel 1 (
        rem Remove the half-built environment so the next launch retries setup.
        rmdir /s /q .venv
        echo [Pixel Forge] Installing requirements failed - see the error above.
        echo [Pixel Forge] Usually no internet for this one-time setup, or the folder path is too long - move it somewhere shorter.
        pause
        exit /b 1
    )
    ".venv\Scripts\python.exe" -c "import tkinter" 2>nul
    if errorlevel 1 (
        echo [Pixel Forge] This Python has no Tkinter. Reinstall Python from python.org with "tcl/tk and IDLE" ticked.
        pause
        exit /b 1
    )
)

rem pythonw runs the app without a console window.
start "" ".venv\Scripts\pythonw.exe" pixel_forge.py %1
