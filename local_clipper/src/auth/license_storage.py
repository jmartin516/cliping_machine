"""
Persistent license storage for CustosAI Clipper.

Stores the validated license key in the app data directory so the user
doesn't need to re-enter it on each launch. Cleared when license expires.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from src.utils.paths import get_app_data_dir

logger = logging.getLogger(__name__)

_LICENSE_FILE = "license.json"
_KEY = "license_key"


def save_license(license_key: str) -> None:
    """Save the license key to persistent storage."""
    try:
        data_dir = get_app_data_dir()
        path = data_dir / _LICENSE_FILE
        with open(path, "w") as f:
            json.dump({_KEY: license_key.strip()}, f)
        logger.debug("License saved")
    except Exception as exc:
        logger.warning("Could not save license: %s", exc)


def load_license() -> str | None:
    """Load the saved license key, or None if not found/invalid."""
    try:
        path = get_app_data_dir() / _LICENSE_FILE
        if not path.exists():
            return None
        with open(path) as f:
            data = json.load(f)
        key = data.get(_KEY)
        return key.strip() if isinstance(key, str) and key.strip() else None
    except Exception as exc:
        logger.debug("Could not load license: %s", exc)
        return None


def clear_license() -> None:
    """Remove the saved license (e.g. when expired or revoked)."""
    try:
        path = get_app_data_dir() / _LICENSE_FILE
        if path.exists():
            path.unlink()
            logger.info("License cleared from storage")
    except Exception as exc:
        logger.warning("Could not clear license: %s", exc)
