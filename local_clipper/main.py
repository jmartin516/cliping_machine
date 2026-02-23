"""
CustosAI Clipper — Application Entry Point

Bootstraps logging, loads environment configuration, and hands off
to the GUI layer. This file is the target for PyInstaller compilation.
"""

from __future__ import annotations

import os
import sys
import warnings

# Suppress known warnings before any imports that trigger them
warnings.filterwarnings("ignore", message=".*OpenSSL.*")
warnings.filterwarnings("ignore", message=".*LibreSSL.*")
os.environ.setdefault("TK_SILENCE_DEPRECATION", "1")

import logging
import platform
from pathlib import Path

# Ensure the project root is on sys.path so `src.*` imports resolve
# both when running from source and from a PyInstaller bundle.
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _check_tk_version() -> bool:
    """
    CustomTkinter requires Tk 8.6+ to render. macOS system Python uses Tk 8.5,
    which creates a blank window. Return False if we should abort.
    """
    if platform.system() != "Darwin":
        return True
    try:
        import tkinter as tk
        # TkVersion is e.g. 8.5 or 8.6 (float)
        if tk.TkVersion < 8.6:
            return False
    except Exception:
        pass
    return True


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("PIL").setLevel(logging.WARNING)
    logging.getLogger("PIL.PngImagePlugin").setLevel(logging.WARNING)


def main() -> None:
    if not _check_tk_version():
        _msg = """
╔══════════════════════════════════════════════════════════════════════════════╗
║  CustosAI Clipper — Tk version incompatible                                  ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Your Python uses Tk 8.5. CustomTkinter requires Tk 8.6+ to render.         ║
║  On macOS, the system Python ships with Tk 8.5, which causes a blank window. ║
║                                                                              ║
║  FIX: Install Python 3.11+ from Homebrew and recreate your venv:            ║
║                                                                              ║
║    brew install python@3.11 python-tk@3.11                                   ║
║    cd local_clipper                                                          ║
║    rm -rf .venv                                                              ║
║    python3.11 -m venv .venv                                                  ║
║    source .venv/bin/activate                                                 ║
║    pip install -r requirements.txt                                          ║
║    python main.py                                                            ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""
        print(_msg)
        sys.exit(1)

    _configure_logging()
    logger = logging.getLogger("local_clipper")
    logger.info("Starting CustosAI Clipper …")

    from src.gui.app import LocalClipperApp

    app = LocalClipperApp()
    app.mainloop()


if __name__ == "__main__":
    main()
