# CustosAI Clipper

A cross-platform desktop application that turns long-form videos into short, vertical (9:16) clips with AI-generated subtitles — entirely offline.

Select a video, pick a Whisper model, and CustosAI Clipper handles the rest: audio extraction, transcription, cropping, interactive subtitle styling, and rendering. The result is a ready-to-upload vertical clip with dynamic, word-by-word highlighted captions burned in.

---

## ⚠️ macOS: Ventana en blanco

Si la app abre pero la ventana está vacía (gris oscuro sin botones ni texto), es porque tu Python usa **Tk 8.5**. CustomTkinter necesita **Tk 8.6+**.

**Solución:**

```bash
brew install python@3.11 python-tk@3.11
cd local_clipper
rm -rf .venv
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

La app detecta Tk 8.5 al arrancar y mostrará estas instrucciones si es necesario.

---

## Features

- **AI Transcription** — Powered by [faster-whisper](https://github.com/SYSTRAN/faster-whisper) running locally. No cloud API, no data leaves your machine.
- **CUDA + Apple Silicon** — Auto-detects NVIDIA GPUs for float16 inference. Falls back to CPU int8, which leverages Apple's Accelerate framework on M-series Macs.
- **9:16 Vertical Crop** — Centres and crops standard 16:9 footage into portrait orientation.
- **Styled Subtitles** — Impact font, white text with thick black stroke, positioned in the lower-middle third. Long lines are auto-wrapped.
- **License Gating** — Activation via [Whop](https://whop.com/) API, bound to a persistent Hardware ID (HWID) to prevent key sharing.
- **Non-blocking UI** — All heavy processing (transcription, rendering) runs on background threads. The GUI stays fully responsive with live progress and console output.
- **Cross-Platform** — Single codebase targeting Windows and macOS.

---

## Project Structure

```
local_clipper/
├── main.py                        # Application entry point
├── requirements.txt               # Pinned dependencies
├── LocalClipper.spec              # PyInstaller build config
├── .env.example                   # Environment variable template
├── assets/                        # icon.ico / icon.icns for app icon
└── src/
    ├── auth/
    │   ├── hwid.py                # Cross-platform Hardware ID extraction
    │   └── whop_api.py            # Whop license validation client
    ├── engine/
    │   ├── ai_transcriber.py       # faster-whisper model loading & transcription
    │   └── video_processor.py     # Crop, subtitle overlay, render pipeline
    ├── gui/
    │   ├── app.py                 # Main window — Login, Setup, Dashboard views
    │   └── components.py          # Reusable widgets (LogConsole, ProgressBar, etc.)
    └── utils/
        └── paths.py               # Path resolution (source vs PyInstaller bundle)
```

---

## Requirements

- **Python 3.10+** (3.11+ recommended on macOS for proper GUI rendering)
- **FFmpeg** — auto-downloaded on first launch (no manual install needed)
- **(Optional) NVIDIA GPU** with CUDA toolkit for GPU-accelerated transcription

> **macOS users:** The system Python (3.9) ships with Tk 8.5, which does not render CustomTkinter correctly. Use Python from Homebrew for best results:
> ```bash
> brew install python@3.11 python-tk@3.11
> ```

---

## Installation

### 1. Prerequisites

FFmpeg is **auto-downloaded** on first launch. No manual installation needed.

### 2. Clone and setup

```bash
git clone https://github.com/your-org/local_clipper.git
cd local_clipper
```

### 3. Create virtual environment

```bash
# Create venv (use python3.11 on macOS if you installed via Homebrew)
python -m venv .venv

# Activate
source .venv/bin/activate   # macOS / Linux
# .venv\Scripts\activate    # Windows
```

### 4. Install dependencies

```bash
pip install -r requirements.txt
```

### 5. Configure environment (optional)

```bash
cp .env.example .env
# Edit .env and set WHOP_API_KEY for license validation
```

---

## Usage

```bash
python main.py
```

The app suppresses common warnings (urllib3/OpenSSL, Tk deprecation) automatically.

### Login Screen

Enter your license key and click **Activate**. The key is validated against the Whop API and bound to your machine's Hardware ID.

### First-Run Setup

After successful activation, the app downloads required components (FFmpeg, optional Whisper model cache). This happens once; subsequent launches skip setup.

### Dashboard

1. **Input Video** — Browse and select any `.mp4`, `.mov`, `.avi`, `.mkv`, or `.webm` file.
2. **Output Folder** — Choose the directory where the rendered clip will be saved.
3. **Whisper Model** — Select a model size from the dropdown:

   | Model | Speed | Accuracy | VRAM |
   |-------|-------|----------|------|
   | `tiny` | Fastest | Lower | ~1 GB |
   | `base` | Fast | Good | ~1 GB |
   | `small` | Moderate | Better | ~2 GB |
   | `medium` | Slow | High | ~5 GB |
   | `large-v2` | Slowest | Highest | ~10 GB |

4. Click **Generate Clip**. The console will show real-time progress:
   - Extracting audio
   - Loading Whisper model (downloaded once and cached at `~/.cache/local_clipper/`)
   - Transcribing segments
   - Rendering the vertical clip with subtitles

The output file is saved as `<original_name>_vertical.mp4` in your chosen folder.

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| **Blank/dark window on macOS** | Use Python 3.11+ from Homebrew (`brew install python@3.11`). System Python 3.9 uses Tk 8.5, which does not render CustomTkinter. |
| **urllib3 / OpenSSL warning** | Handled automatically. If it persists, ensure `urllib3>=1.26.0,<2` is in `requirements.txt` and run `pip install -r requirements.txt`. |
| **Tk deprecation warning** | The app sets `TK_SILENCE_DEPRECATION=1` automatically. |
| **Window icon not applied** | Optional. Add `assets/icon.png` (macOS) or `assets/icon.ico` (Windows) if you want a custom icon. |
| **FFmpeg not found** | The app auto-downloads FFmpeg on first launch. If setup fails, check your internet connection and retry. |

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `WHOP_API_BASE` | Whop API v2 base URL (default: https://api.whop.com/api/v2) |
| `WHOP_API_KEY` | Bearer token for Whop API authentication |

---

## Architecture Notes

### Threading Model

The application uses `customtkinter` for the UI and Python's `threading` module for all blocking operations:

- **License validation** — runs on a daemon thread; result posted back via `after_idle`.
- **Video pipeline** (extract → transcribe → render) — runs on a daemon thread. The `LogConsole.write()` and `StatusProgressBar.set_progress()` widgets are thread-safe; they schedule Tk mutations through `after_idle` internally.
- The Generate button is disabled during processing and re-enabled in a `finally` block to guarantee recovery even on errors.

### Hardware ID

| Platform | Method | Persistence |
|----------|--------|-------------|
| Windows | `wmic csproduct get UUID` with PowerShell fallback | Survives OS reinstalls |
| macOS | `ioreg` → `IOPlatformUUID` | Survives OS reinstalls |
| Other | SHA-256 of hostname + MAC | Less stable |

### Cross-Platform Considerations

- All file paths use `pathlib.Path` — no hardcoded slashes.
- Window icon: `.ico` on Windows, skipped on macOS (icon is embedded at `.app` bundle level by PyInstaller).
- Font resolution: tries Impact → Arial Black → Helvetica Bold → DejaVu Sans Bold.

---

## Building a Standalone Executable

```bash
cd local_clipper
./build.sh   # Uses Python 3.11+ and builds (macOS: requires brew install python@3.11 python-tk@3.11)
```

Or manually:
```bash
cd local_clipper
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt pyinstaller
python -m PyInstaller LocalClipper.spec
```

**Output:** `dist/LocalClipper.app` (macOS) or `dist/LocalClipper.exe` (Windows)

**End users need nothing:** Python, FFmpeg, and Whisper model are bundled or auto-downloaded on first launch. No terminal required.

---

## License

Proprietary. Distributed under commercial license via [Whop](https://whop.com/).
