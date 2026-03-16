"""
CustosAI Clipper — Application Entry Point

Simple version for testing market fit.
Features: Single-instance lock, license validation, video processing.
Version: 1.0.0
"""

from __future__ import annotations

import os
import sys
import tempfile
import warnings
from pathlib import Path

# Prevent double launch on macOS
if sys.platform == "darwin":
    import multiprocessing
    try:
        multiprocessing.set_start_method('spawn', force=True)
    except RuntimeError:
        pass

if getattr(sys, "frozen", False):
    _writable_cwd = Path(tempfile.gettempdir()) / "CustosAI-Clipper"
    _writable_cwd.mkdir(parents=True, exist_ok=True)
    os.chdir(str(_writable_cwd))

warnings.filterwarnings("ignore", message=".*OpenSSL.*")
warnings.filterwarnings("ignore", message=".*LibreSSL.*")
os.environ.setdefault("TK_SILENCE_DEPRECATION", "1")

import logging
import platform
import atexit
import time

if getattr(sys, "frozen", False):
    _ROOT = Path(sys._MEIPASS)
else:
    _ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

APP_VERSION = "1.0.0"
_lock_file_handle = None


def _try_single_instance_lock() -> bool:
    """Prevent multiple app instances."""
    global _lock_file_handle
    
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))
    
    from src.utils.paths import get_app_data_dir
    
    lock_dir = get_app_data_dir()
    lock_file = lock_dir / ".single_instance.lock"
    pid_file = lock_dir / ".instance.pid"
    
    try:
        if pid_file.exists():
            try:
                old_pid = int(pid_file.read_text().strip())
                if old_pid != os.getpid():
                    try:
                        import psutil
                        if psutil.pid_exists(old_pid):
                            proc = psutil.Process(old_pid)
                            cmdline = " ".join(proc.cmdline())
                            if "LocalClipper" in cmdline or "LocalClipper.real" in cmdline:
                                print("LocalClipper is already running.", file=sys.stderr)
                                return False
                    except (ImportError, Exception):
                        try:
                            os.kill(old_pid, 0)
                            print("LocalClipper is already running.", file=sys.stderr)
                            return False
                        except (OSError, ProcessLookupError):
                            pass
            except (ValueError, Exception):
                pass
        
        if sys.platform == "win32":
            import msvcrt
            _lock_file_handle = open(lock_file, "w")
            try:
                msvcrt.locking(_lock_file_handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                _lock_file_handle.close()
                _lock_file_handle = None
                return False
        else:
            import fcntl
            _lock_file_handle = open(lock_file, "w")
            try:
                fcntl.lockf(_lock_file_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (IOError, OSError):
                _lock_file_handle.close()
                _lock_file_handle = None
                return False
        
        pid_file.write_text(str(os.getpid()))
        atexit.register(_cleanup_lock, lock_file, pid_file)
        return True
        
    except Exception as e:
        print(f"Single instance lock failed: {e}", file=sys.stderr)
        return False


def _cleanup_lock(lock_file: Path, pid_file: Path) -> None:
    """Clean up lock files on exit."""
    global _lock_file_handle
    try:
        if _lock_file_handle:
            _lock_file_handle.close()
        pid_file.unlink(missing_ok=True)
    except Exception:
        pass


def _check_tk_version() -> bool:
    """Check Tk 8.6+ for CustomTkinter."""
    if platform.system() != "Darwin":
        return True
    try:
        import tkinter as tk
        tcl = tk.Tcl()
        patchlevel = tcl.eval('info patchlevel')
        version_parts = patchlevel.split('.')
        if int(version_parts[0]) < 8 or (int(version_parts[0]) == 8 and int(version_parts[1]) < 6):
            return False
    except Exception:
        pass
    return True


def _configure_logging() -> None:
    """Configure logging."""
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("PIL").setLevel(logging.WARNING)


def main() -> None:
    """Main entry point."""
    time.sleep(0.05)
    
    if not _try_single_instance_lock():
        sys.exit(0)

    if not _check_tk_version():
        print("Error: Tk 8.6+ required")
        sys.exit(1)

    _configure_logging()
    logger = logging.getLogger("local_clipper")
    logger.info(f"Starting CustosAI Clipper v{APP_VERSION}")

    from src.gui.app import LocalClipperApp
    
    app = LocalClipperApp()
    app.mainloop()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
