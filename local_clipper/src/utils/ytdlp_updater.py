"""
yt-dlp standalone binary updater for CustosAI Clipper.

Fetches config from the public GitHub repo and downloads the appropriate
yt-dlp binary for the platform. This allows updating yt-dlp when YouTube
breaks without rebuilding the app.
"""

from __future__ import annotations

import logging
import os
import platform
import stat
import sys
from pathlib import Path
from typing import Callable, Optional

import requests

from src.utils.paths import get_ytdlp_bin_dir

logger = logging.getLogger(__name__)

LogCallback = Callable[[str, str], None]

_CONFIG_URL = "https://raw.githubusercontent.com/jmartin516/custosai-clipper-config/main/config.json"
_REQUEST_TIMEOUT = 15


def _get_platform_key() -> str:
    """Return the config key for this platform (windows, macos_intel, macos_arm64)."""
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos_arm64" if platform.machine().lower() in ("arm64", "aarch64") else "macos_intel"
    return "macos_intel"  # fallback for linux


def _get_ytdlp_binary_name() -> str:
    """Return the expected binary filename for this platform."""
    if sys.platform == "win32":
        return "yt-dlp.exe"
    return "yt-dlp"


def get_or_update_ytdlp_binary(on_log: Optional[LogCallback] = None) -> Optional[Path]:
    """
    Return the path to the yt-dlp standalone binary, downloading it if needed.

    Fetches config from the public GitHub repo, downloads the binary for this
    platform, and saves it to the app data directory. If download fails,
    returns None (caller should fall back to the bundled Python library).

    Returns:
        Path to the yt-dlp binary, or None if unavailable.
    """
    def _log(msg: str, level: str = "info") -> None:
        getattr(logger, level)(msg)
        if on_log:
            on_log(msg, level)

    bin_dir = get_ytdlp_bin_dir()
    platform_key = _get_platform_key()
    binary_name = _get_ytdlp_binary_name()
    binary_path = bin_dir / binary_name
    version_file = bin_dir / "version.txt"

    try:
        _log("Checking for yt-dlp updates…", "debug")
        resp = requests.get(_CONFIG_URL, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        config = resp.json()
    except Exception as exc:
        _log(f"Could not fetch yt-dlp config: {exc}", "warning")
        if binary_path.exists():
            _log("Using existing yt-dlp binary", "debug")
            return binary_path
        return None

    yt_dlp_config = config.get("yt_dlp", {})
    download_urls = yt_dlp_config.get("download_urls", {})
    remote_version = yt_dlp_config.get("version", "unknown")
    download_url = download_urls.get(platform_key)

    if not download_url:
        _log(f"No download URL for platform {platform_key}", "warning")
        if binary_path.exists():
            return binary_path
        return None

    # Use existing binary if version matches
    if binary_path.exists() and version_file.exists():
        try:
            local_version = version_file.read_text().strip()
            if local_version == remote_version:
                _log(f"yt-dlp {local_version} already up to date", "debug")
                return binary_path
        except Exception:
            pass

    # Download the binary
    _log(f"Downloading yt-dlp {remote_version}…", "info")
    try:
        resp = requests.get(download_url, timeout=60, stream=True)
        resp.raise_for_status()
        content = resp.content
    except Exception as exc:
        _log(f"Could not download yt-dlp: {exc}", "warning")
        if binary_path.exists():
            return binary_path
        return None

    try:
        binary_path.write_bytes(content)
        version_file.write_text(remote_version)

        # Make executable on Unix
        if sys.platform != "win32":
            binary_path.chmod(stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH | stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)

        _log(f"yt-dlp {remote_version} ready at {binary_path}", "info")
        return binary_path
    except Exception as exc:
        _log(f"Could not save yt-dlp binary: {exc}", "warning")
        return None
