# CustosAI Clipper

A cross-platform desktop application that turns long-form videos into short, vertical (9:16) clips with AI-generated subtitles — entirely offline.

Select a video, pick a Whisper model, and CustosAI Clipper handles the rest: audio extraction, transcription, cropping, interactive subtitle styling, and rendering. The result is a ready-to-upload vertical clip with dynamic, word-by-word highlighted captions burned in.

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
├── .env.example                   # Environment variable template
├── assets/                        # (Optional) icon.ico / icon.icns
└── src/
    ├── auth/
    │   ├── hwid.py                # Cross-platform Hardware ID extraction
    │   └── whop_api.py            # Whop license validation client
    ├── engine/
    │   ├── ai_transcriber.py      # faster-whisper model loading & transcription
    │   └── video_processor.py     # Crop, subtitle overlay, render pipeline
    └── gui/
        ├── app.py                 # Main window — Login & Dashboard views
        └── components.py          # Reusable widgets (LogConsole, ProgressBar, etc.)
```

---

## Requirements

- **Python 3.10+**
- **FFmpeg** — must be available on your system `PATH`.
  - macOS: `brew install ffmpeg`
  - Windows: download from [ffmpeg.org](https://ffmpeg.org/download.html) and add to PATH.
- **(Optional) NVIDIA GPU** with CUDA toolkit for GPU-accelerated transcription.

---

## Installation

```bash
# 1. Clone the repository
git clone https://github.com/your-org/local_clipper.git
cd local_clipper

# 2. Create a virtual environment
python -m venv .venv
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate         # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env and set your WHOP_API_KEY
```

---

## Usage

```bash
python main.py
```

### Login Screen

Enter your license key and click **Activate**. The key is validated against the Whop API and bound to your machine's Hardware ID. The dashboard will not load until validation succeeds.

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

## Environment Variables

| Variable | Description |
|----------|-------------|
| `WHOP_API_URL` | Whop membership validation endpoint |
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
# Install build tools (not included in requirements.txt)
pip install pyinstaller pyarmor

# (Optional) Obfuscate source
pyarmor gen --pack onefile src/

# Build with PyInstaller
pyinstaller --onefile --windowed --name "LocalClipper" \
    --icon assets/icon.ico \          # Windows
    --add-data ".env:." \
    main.py
```

The resulting executable will be in `dist/LocalClipper`.

> **Note:** On macOS, replace `--icon assets/icon.ico` with `--icon assets/icon.icns` and the output will be a `.app` bundle.

---

## License

Proprietary. Distributed under commercial license via [Whop](https://whop.com/).
