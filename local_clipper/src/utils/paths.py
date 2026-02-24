"""
Path resolution for CustosAI Clipper.

When running from source, paths are relative to the project root.
When running from a PyInstaller bundle, resources are extracted to sys._MEIPASS.
"""

from __future__ import annotations

import sys
from pathlib import Path


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
