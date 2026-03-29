@echo off
REM CustosAI Clipper — Build script for Windows
REM Run from local_clipper: build.bat
REM Output: dist\LocalClipper\LocalClipper.exe

cd /d "%~dp0"

echo === CustosAI Clipper — Build Windows ===

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Install Python 3.10+ from python.org
    pause
    exit /b 1
)

REM Create venv if needed
if not exist ".venv\Scripts\activate.bat" (
    echo Creating virtual environment...
    python -m venv .venv
)

echo Activating venv...
call .venv\Scripts\activate.bat

REM Install dependencies
echo Installing dependencies...
pip install -q -r requirements.txt pyinstaller

REM Verify mandatory packages (numpy, llama-cpp-python)
echo Verifying mandatory packages...
python -c "import numpy; import llama_cpp; print('  numpy, llama_cpp OK')"
if errorlevel 1 (
    echo ERROR: Missing numpy or llama-cpp-python. Run: pip install -r requirements.txt
    pause
    exit /b 1
)

REM Pre-download FFmpeg for bundling (no download on first launch)
echo Pre-downloading FFmpeg...
python scripts\setup_ffmpeg_bundle.py

REM Generate icon.ico from assets\icon.png
echo Generating app icons...
python scripts\setup_icons.py

REM Check .env exists
if not exist ".env" (
    echo.
    echo WARNING: .env not found. Copy .env.example to .env and add WHOP_API_KEY.
    echo Optionally add ADMIN_LICENSE_KEY for your personal admin access.
    echo Build will continue but license validation may not work.
    pause
)

REM Build
echo Building with PyInstaller...
python -m PyInstaller LocalClipper.spec

if errorlevel 1 (
    echo Build failed.
    pause
    exit /b 1
)

echo.
echo === Build complete ===
echo Output: dist\LocalClipper\LocalClipper.exe
echo.
echo To create ZIP: Right-click dist\LocalClipper -^> Send to -^> Compressed folder
echo Or run: powershell Compress-Archive -Path dist\LocalClipper -DestinationPath CustosAI-Clipper-Windows.zip
echo.
pause
