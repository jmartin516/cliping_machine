"""
Local Clipper — Application Entry Point

Bootstraps logging, loads environment configuration, and hands off
to the GUI layer. This file is the target for PyInstaller compilation.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Ensure the project root is on sys.path so `src.*` imports resolve
# both when running from source and from a PyInstaller bundle.
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )


def main() -> None:
    _configure_logging()
    logger = logging.getLogger("local_clipper")
    logger.info("Starting Local Clipper …")

    print("[DEBUG main] About to import LocalClipperApp")
    try:
        from src.gui.app import LocalClipperApp
        print("[DEBUG main] Import succeeded")
    except Exception as e:
        print(f"[DEBUG main] Import FAILED: {e}")
        import traceback; traceback.print_exc()
        return

    print("[DEBUG main] Creating LocalClipperApp instance...")
    try:
        app = LocalClipperApp()
        print("[DEBUG main] App created, entering mainloop")
    except Exception as e:
        print(f"[DEBUG main] App creation FAILED: {e}")
        import traceback; traceback.print_exc()
        return

    app.mainloop()


if __name__ == "__main__":
    main()
