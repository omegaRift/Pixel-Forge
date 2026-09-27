@echo off
rem ------------------------------------------------------------------
rem  Pixel Forge - optional AI background removal (rembg + ISNet).
rem  One-time setup that needs internet: about 360 MB of Python
rem  packages plus a 179 MB model saved in the "models" folder.
rem  Afterwards the AI option runs fully offline.
rem ------------------------------------------------------------------
title Pixel Forge - AI setup
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [Pixel Forge] Run start.bat once first to set up Python.
    pause
    exit /b 1
)

echo [Pixel Forge] Installing AI packages - this can take a few minutes...
".venv\Scripts\python.exe" -m pip install -q -r requirements-ai.txt
if errorlevel 1 (
    echo [Pixel Forge] Installing the AI packages failed - see the error above.
    pause
    exit /b 1
)

echo [Pixel Forge] Downloading the AI model if needed (179 MB)...
".venv\Scripts\python.exe" -c "import os, pixel_core as pc; os.environ['U2NET_HOME'] = str(pc.APP_DIR); from rembg import new_session; new_session(pc.AI_MODEL); print('[Pixel Forge] Model ready:', pc.AI_MODEL_FILE)"
if errorlevel 1 (
    echo [Pixel Forge] Downloading the model failed - check your internet connection and run this again.
    pause
    exit /b 1
)

echo.
echo [Pixel Forge] AI background removal is ready. In the app choose Remove BG: AI.
pause
