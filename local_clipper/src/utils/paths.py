"""
Path resolution for CustosAI Clipper.

When running from source, paths are relative to the project root.
When running from a PyInstaller bundle, resources are extracted to sys._MEIPASS.
"""

from __future__ import annotations

import platform
import sys
from pathlib import Path


def _get_platform_key() -> str:
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


def get_base_path() -> Path:
    """
    Return the base directory for app resources (assets, .env, etc.).

    - From source: project root (parent of main.py).
    - From PyInstaller bundle: sys._MEIPASS (temp extraction dir).
    """
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    # Assume we're in src/utils/paths.py → project root is parents[2]
    return Path(__file__).resolve().parents[2]


def get_assets_path() -> Path:
    """Return the assets directory (icons, etc.)."""
    return get_base_path() / "assets"


def get_env_path() -> Path:
    """Return the path to the .env file."""
    return get_base_path() / ".env"


def get_bundled_ffmpeg_dir() -> Path | None:
    """
    Return the path to bundled FFmpeg binaries, or None if not bundled.

    When the app is built with FFmpeg pre-bundled, returns the directory
    containing ffmpeg and ffprobe. Otherwise returns None (app will download).
    """
    if not getattr(sys, "frozen", False):
        return None
    base = get_base_path()
    platform_key = _get_platform_key()
    ffmpeg_dir = base / "ffmpeg_bundle" / platform_key
    crumb = ffmpeg_dir / "installed.crumb"
    if crumb.exists():
        return ffmpeg_dir.resolve()
    return None
