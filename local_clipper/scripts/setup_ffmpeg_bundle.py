#!/usr/bin/env python3
"""
Pre-download FFmpeg binaries for bundling into the app.
Run before PyInstaller so the app ships with FFmpeg — no download on first launch.

Output: ffmpeg_bundle/PLATFORM/ (ffmpeg, ffprobe, installed.crumb)
"""

from __future__ import annotations

import logging
import platform
import stat
import sys
import zipfile
from pathlib import Path

import requests

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# Project root
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
BUNDLE_DIR = PROJECT_ROOT / "ffmpeg_bundle"

PLATFORM_ZIP_URLS = {
    "win32": "https://github.com/zackees/ffmpeg_bins/raw/main/v8.0/win32.zip",
    "darwin": "https://github.com/zackees/ffmpeg_bins/raw/main/v8.0/darwin.zip",
    "darwin_arm64": "https://github.com/zackees/ffmpeg_bins/raw/main/v8.0/darwin_arm64.zip",
    "linux": "https://github.com/zackees/ffmpeg_bins/raw/main/v8.0/linux.zip",
    "linux_arm64": "https://github.com/zackees/ffmpeg_bins/raw/main/v8.0/linux_arm64.zip",
}


def get_platform_key() -> str:
    """Match static_ffmpeg's platform detection."""
    machine = platform.machine().lower()
    is_arm = machine in ("arm64", "aarch64")
    if sys.platform == "win32":
        return "win32"
    if sys.platform == "darwin":
        return "darwin_arm64" if is_arm else "darwin"
    if sys.platform == "linux":
        return "linux_arm64" if is_arm else "linux"
    return sys.platform


def main() -> None:
    platform_key = get_platform_key()
    if platform_key not in PLATFORM_ZIP_URLS:
        raise OSError(f"Unsupported platform: {platform_key}")

    out_dir = BUNDLE_DIR / platform_key
    out_dir.mkdir(parents=True, exist_ok=True)

    # Check if already installed
    crumb = out_dir / "installed.crumb"
    if crumb.exists():
        logger.info("FFmpeg already bundled at %s", out_dir)
        return

    url = PLATFORM_ZIP_URLS[platform_key]
    zip_path = out_dir.with_suffix(".zip")

    logger.info("Pre-downloading FFmpeg for %s...", platform_key)
    try:
        resp = requests.get(url, stream=True, timeout=600)
        resp.raise_for_status()
        total = int(resp.headers.get("content-length", 0))
        with open(zip_path, "wb") as f:
            downloaded = 0
            for chunk in resp.iter_content(chunk_size=262144):
                f.write(chunk)
                downloaded += len(chunk)
                if total and downloaded % (1024 * 1024) < len(chunk):
                    pct = 100 * downloaded / total
                    logger.info("  %.0f%%", pct)

        install_parent = out_dir.parent
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(install_parent)

        zip_path.unlink(missing_ok=True)

        # Fix permissions on Unix
        if sys.platform != "win32":
            for exe in ("ffmpeg", "ffprobe"):
                exe_path = out_dir / exe
                if exe_path.exists():
                    exe_path.chmod(
                        stat.S_IXOTH | stat.S_IXUSR | stat.S_IXGRP
                        | stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH
                    )

        crumb.write_text(f"installed from {url}\n")
        logger.info("FFmpeg ready: %s", out_dir)
    except Exception as exc:
        logger.error("Failed to download FFmpeg: %s", exc)
        raise


if __name__ == "__main__":
    main()
