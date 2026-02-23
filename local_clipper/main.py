"""
CustosAI Clipper — Application Entry Point

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
    logging.getLogger("PIL").setLevel(logging.WARNING)
    logging.getLogger("PIL.PngImagePlugin").setLevel(logging.WARNING)


def main() -> None:
    _configure_logging()
    logger = logging.getLogger("local_clipper")
    logger.info("Starting CustosAI Clipper …")

    from src.gui.app import LocalClipperApp

    app = LocalClipperApp()
    app.mainloop()


if __name__ == "__main__":
    main()
