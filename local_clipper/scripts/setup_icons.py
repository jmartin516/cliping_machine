#!/usr/bin/env python3
"""
Generate icon.icns (macOS) and icon.ico (Windows) from assets/icon.png.
Run before PyInstaller so the app bundle has the correct icon.
"""

from __future__ import annotations

import logging
import platform
import subprocess
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
ASSETS = PROJECT_ROOT / "assets"
ICON_PNG = ASSETS / "icon.png"


def generate_ico() -> bool:
    """Generate icon.ico from icon.png using Pillow."""
    try:
        from PIL import Image

        img = Image.open(ICON_PNG).convert("RGBA")
        out_path = ASSETS / "icon.ico"
        sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
        img.save(out_path, format="ICO", sizes=sizes)
        logger.info("Created %s", out_path)
        return True
    except Exception as exc:
        logger.warning("Could not create icon.ico: %s", exc)
        return False


def generate_icns() -> bool:
    """Generate icon.icns from icon.png using Pillow + macOS iconutil."""
    if platform.system() != "Darwin":
        logger.info("Skipping icon.icns (macOS only)")
        return False

    try:
        from PIL import Image

        img = Image.open(ICON_PNG).convert("RGBA")
    except Exception as exc:
        logger.warning("Could not load icon.png for icns: %s", exc)
        return False

    iconset = ASSETS / "icon.iconset"
    if iconset.exists():
        for f in iconset.iterdir():
            f.unlink()
    else:
        iconset.mkdir()

    # Required iconset structure for iconutil
    sizes = [
        (16, "icon_16x16.png"),
        (32, "icon_16x16@2x.png"),
        (32, "icon_32x32.png"),
        (64, "icon_32x32@2x.png"),
        (128, "icon_128x128.png"),
        (256, "icon_128x128@2x.png"),
        (256, "icon_256x256.png"),
        (512, "icon_256x256@2x.png"),
        (512, "icon_512x512.png"),
        (1024, "icon_512x512@2x.png"),
    ]

    try:
        for size, name in sizes:
            resized = img.resize((size, size), Image.Resampling.LANCZOS)
            resized.save(iconset / name, "PNG")
        out_icns = ASSETS / "icon.icns"
        result = subprocess.run(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(out_icns)],
            capture_output=True,
            text=True,
        )
        # Cleanup iconset
        for f in iconset.iterdir():
            f.unlink()
        iconset.rmdir()
        if result.returncode != 0:
            logger.warning("iconutil failed: %s", result.stderr or result.stdout)
            return False
        logger.info("Created %s", out_icns)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, OSError) as exc:
        logger.warning("Could not create icon.icns: %s", exc)
        if iconset.exists():
            for f in iconset.iterdir():
                f.unlink()
            iconset.rmdir()
        return False


def main() -> None:
    if not ICON_PNG.exists():
        logger.warning("No icon.png in assets — skipping icon generation")
        return

    generate_ico()
    generate_icns()


if __name__ == "__main__":
    main()
