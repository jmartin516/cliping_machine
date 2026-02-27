#!/usr/bin/env bash
# CustosAI Clipper — Build script for distribution
# Ensures Python 3.11+ with Tk 8.6+ so the bundled app works for end users.
# Run from local_clipper/: ./build.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== CustosAI Clipper — Build ==="

# Find Python 3.11+ with Tk 8.6+ (required for CustomTkinter on macOS)
PYTHON=""
for cmd in python3.12 python3.11 python3; do
    if command -v "$cmd" &>/dev/null; then
        ver=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || true)
        if [ -n "$ver" ]; then
            major=$(echo "$ver" | cut -d. -f1)
            minor=$(echo "$ver" | cut -d. -f2)
            if [ "$major" -ge 3 ] && [ "$minor" -ge 11 ]; then
                # Check Tk version (must be 8.6+ for CustomTkinter)
                if $cmd -c "import tkinter; exit(0 if tkinter.TkVersion >= 8.6 else 1)" 2>/dev/null; then
                    PYTHON="$cmd"
                    tk_ver=$("$cmd" -c "import tkinter; print(tkinter.TkVersion)" 2>/dev/null || echo "?")
                    echo "Using $PYTHON (Tk $tk_ver)"
                    break
                fi
            fi
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo ""
    echo "ERROR: Python 3.11+ with Tk 8.6+ is required to build."
    echo "On macOS, install from Homebrew:"
    echo "  brew install python@3.11 python-tk@3.11"
    echo ""
    echo "Then run this script again."
    exit 1
fi

# Create venv if needed
if [ ! -d ".venv" ] || [ ! -f ".venv/bin/activate" ]; then
    echo "Creating virtual environment..."
    $PYTHON -m venv .venv
fi

echo "Activating venv..."
source .venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install -q -r requirements.txt pyinstaller

# Verify mandatory packages (numpy, llama-cpp-python) are importable
echo "Verifying mandatory packages..."
python -c "
import sys
err = []
try:
    import numpy
except ImportError:
    err.append('numpy')
try:
    import llama_cpp
except ImportError:
    err.append('llama-cpp-python')
if err:
    print('ERROR: Missing mandatory packages:', ', '.join(err))
    print('Run: pip install -r requirements.txt')
    sys.exit(1)
print('  numpy, llama_cpp OK')
"

# Pre-download FFmpeg for bundling (no download on first launch)
echo "Pre-downloading FFmpeg..."
python scripts/setup_ffmpeg_bundle.py

# Generate icon.icns and icon.ico from assets/icon.png (optional; may already exist)
echo "Generating app icons..."
python scripts/setup_icons.py || true

# Build
echo "Building with PyInstaller..."
python -m PyInstaller -y LocalClipper.spec

# macOS: fix Tk crash when launched from Finder (pty launcher, single Dock icon)
if [ "$(uname)" = "Darwin" ] && [ -d "dist/LocalClipper.app" ]; then
    bash scripts/apply_macos_tk_fix.sh || true
fi

# Firma en macOS (ad-hoc por defecto; ver scripts/sign_and_notarize.sh para Developer ID)
if [ "$(uname)" = "Darwin" ] && [ -d "dist/LocalClipper.app" ]; then
    echo "Firmando app para macOS..."
    bash scripts/sign_and_notarize.sh || echo "(Firma opcional falló; la app funcionará con clic derecho → Abrir)"
fi

echo ""
echo "=== Build complete ==="
echo "Output: dist/LocalClipper (macOS) or dist/LocalClipper.exe (Windows)"
echo ""
echo "Run the app: ./dist/LocalClipper  (or open dist/LocalClipper.app if it exists)"
echo ""
