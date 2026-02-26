"""
CustosAI Clipper — Application Entry Point

Bootstraps logging, loads environment configuration, and hands off
to the GUI layer. This file is the target for PyInstaller compilation.
"""

from __future__ import annotations

import os
import sys
import tempfile
import warnings
from pathlib import Path

# When running from a DMG/bundle, cwd may be the read-only mount. Set to a writable dir.
if getattr(sys, "frozen", False):
    _writable_cwd = Path(tempfile.gettempdir()) / "CustosAI-Clipper"
    _writable_cwd.mkdir(parents=True, exist_ok=True)
    os.chdir(str(_writable_cwd))

# Suppress known warnings before any imports that trigger them
warnings.filterwarnings("ignore", message=".*OpenSSL.*")
warnings.filterwarnings("ignore", message=".*LibreSSL.*")
os.environ.setdefault("TK_SILENCE_DEPRECATION", "1")

import logging
import platform

# Ensure the project root is on sys.path so `src.*` imports resolve
# both when running from source and from a PyInstaller bundle.
if getattr(sys, "frozen", False):
    _ROOT = Path(sys._MEIPASS)
else:
    _ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


_lock_file_handle = None  # Keep open so lock persists for process lifetime


def _try_single_instance_lock() -> bool:
    """
    Acquire a single-instance lock. Return True if we got it (first instance).
    Return False if another instance is already running — caller should exit.
    """
    global _lock_file_handle
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))
    from src.utils.paths import get_app_data_dir
    lock_file = get_app_data_dir() / ".single_instance.lock"
    try:
        if sys.platform == "win32":
            import msvcrt
            _lock_file_handle = open(lock_file, "w")
            try:
                msvcrt.locking(_lock_file_handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                _lock_file_handle.close()
                _lock_file_handle = None
                return False
            return True
        else:
            import fcntl
            _lock_file_handle = open(lock_file, "w")
            try:
                fcntl.lockf(_lock_file_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (IOError, OSError):
                _lock_file_handle.close()
                _lock_file_handle = None
                return False
            return True
    except Exception:
        if _lock_file_handle:
            try:
                _lock_file_handle.close()
            except Exception:
                pass
            _lock_file_handle = None
        return True  # If lock fails for other reasons, allow launch


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
    if not _try_single_instance_lock():
        sys.exit(0)  # Another instance already running

    if not _check_tk_version():
        # Different message for bundled app vs running from source
        if getattr(sys, "frozen", False):
            _msg = """
╔══════════════════════════════════════════════════════════════════════════════╗
║  CustosAI Clipper — Incompatible con tu sistema                              ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Esta versión de la app no es compatible con tu Mac.                         ║
║                                                                              ║
║  Por favor descarga la versión más reciente desde Whop o contacta soporte.   ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""
        else:
            _msg = """
╔══════════════════════════════════════════════════════════════════════════════╗
║  CustosAI Clipper — Tk version incompatible                                  ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Tu Python usa Tk 8.5. CustomTkinter requiere Tk 8.6+ para funcionar.       ║
║  En macOS, el Python del sistema trae Tk 8.5.                               ║
║                                                                              ║
║  SOLUCIÓN: Instala Python 3.11+ desde Homebrew:                              ║
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
    import multiprocessing
    multiprocessing.freeze_support()
    main()
