"""
CustosAI Clipper — Application Entry Point (CORREGIDO)

FIXES aplicados:
1. Multiprocessing start method 'spawn' para macOS (evita fork issues)
2. Single instance lock robusto con verificación de proceso activo
3. Fail-closed en caso de errores del lock
4. Delay inicial para prevenir race conditions
"""

from __future__ import annotations

import os
import sys
import tempfile
import warnings
from pathlib import Path

# ═══════════════════════════════════════════════════════════════════════════════
# FIX CRÍTICO #1: Configurar multiprocessing ANTES de cualquier otra importación
# ═══════════════════════════════════════════════════════════════════════════════
if sys.platform == "darwin":
    import multiprocessing
    try:
        multiprocessing.set_start_method('spawn', force=True)
    except RuntimeError:
        pass  # Ya fue configurado

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
import atexit

# Ensure the project root is on sys.path so `src.*` imports resolve
if getattr(sys, "frozen", False):
    _ROOT = Path(sys._MEIPASS)
else:
    _ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ═══════════════════════════════════════════════════════════════════════════════
# FIX CRÍTICO #2: Single Instance Lock Robusto
# ═══════════════════════════════════════════════════════════════════════════════

_lock_file_handle = None  # Keep open so lock persists for process lifetime


def _try_single_instance_lock() -> bool:
    """
    Acquire a single-instance lock with process verification.
    
    CRITICAL FIXES:
    - Verifica que no haya otra instancia realmente corriendo (via PID)
    - Fail-closed: retorna False en caso de error (no True)
    - Limpia archivos stale de bloqueos anteriores
    """
    global _lock_file_handle
    
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))
    
    from src.utils.paths import get_app_data_dir
    
    lock_dir = get_app_data_dir()
    lock_file = lock_dir / ".single_instance.lock"
    pid_file = lock_dir / ".instance.pid"
    
    try:
        # Verificar si hay otra instancia activa
        if pid_file.exists():
            try:
                old_pid = int(pid_file.read_text().strip())
                if old_pid != os.getpid():
                    # Intentar verificar si el proceso existe
                    try:
                        import psutil
                        if psutil.pid_exists(old_pid):
                            proc = psutil.Process(old_pid)
                            cmdline = " ".join(proc.cmdline())
                            if "LocalClipper" in cmdline or "LocalClipper.real" in cmdline:
                                print("LocalClipper is already running.", file=sys.stderr)
                                return False
                    except (ImportError, Exception):
                        # Sin psutil, usar método básico
                        try:
                            os.kill(old_pid, 0)  # Verificar si existe
                            print("LocalClipper is already running.", file=sys.stderr)
                            return False
                        except (OSError, ProcessLookupError):
                            pass  # Proceso no existe, continuar
            except (ValueError, Exception):
                pass  # Archivo corrupto, ignorar
        
        # Platform-specific file locking
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
        
        # Escribir PID actual
        pid_file.write_text(str(os.getpid()))
        
        # Registrar cleanup al salir
        atexit.register(_cleanup_lock, lock_file, pid_file)
        return True
        
    except Exception as e:
        # CRITICAL FIX: Fail closed - no permitir ejecución si hay dudas
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
    """
    CustomTkinter requires Tk 8.6+ to render. macOS system Python uses Tk 8.5,
    which creates a blank window. Return False if we should abort.
    """
    if platform.system() != "Darwin":
        return True
    try:
        import tkinter as tk
        # FIX: Usar Tcl().eval para obtener versión exacta
        tcl = tk.Tcl()
        patchlevel = tcl.eval('info patchlevel')
        version_parts = patchlevel.split('.')
        if int(version_parts[0]) < 8 or (int(version_parts[0]) == 8 and int(version_parts[1]) < 6):
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
    # FIX CRÍTICO #3: Delay inicial para prevenir race conditions
    # cuando macOS lanza múltiples eventos de apertura rápidamente
    import time
    time.sleep(0.05)
    
    if not _try_single_instance_lock():
        sys.exit(0)  # Another instance already running

    if not _check_tk_version():
        if getattr(sys, "frozen", False):
            _msg = """
╔══════════════════════════════════════════════════════════════════════════════╗
║  CustosAI Clipper — Incompatible with your system                            ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  This version is not compatible with your Mac.                               ║
║                                                                              ║
║  Please download the latest version from Whop or contact support.            ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""
        else:
            _msg = """
╔══════════════════════════════════════════════════════════════════════════════╗
║  CustosAI Clipper — Tk version incompatible                                  ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Your Python uses Tk 8.5. CustomTkinter requires Tk 8.6+ to work.            ║
║  On macOS, system Python ships with Tk 8.5.                                  ║
║                                                                              ║
║  SOLUTION: Install Python 3.11+ from Homebrew:                               ║
║                                                                              ║
║    brew install python@3.11 python-tk@3.11                                   ║
║    cd local_clipper                                                          ║
║    rm -rf .venv                                                              ║
║    python3.11 -m venv .venv                                                  ║
║    source .venv/bin/activate                                                 ║
║    pip install -r requirements.txt                                           ║
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
    multiprocessing.freeze_support()
    main()
