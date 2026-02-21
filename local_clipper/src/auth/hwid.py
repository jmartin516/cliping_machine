"""
Hardware ID (HWID) extraction module.

Provides a persistent, unique machine identifier that survives OS reinstalls
where possible. Uses motherboard/platform UUID — the most reliable identifier
that is independent of drives, NICs, or peripheral changes.

Supported platforms:
    - Windows  → WMI `csproduct get UUID`
    - macOS    → IOKit `IOPlatformUUID`
    - Fallback → deterministic UUID derived from hostname + MAC (less stable)
"""

from __future__ import annotations

import hashlib
import logging
import platform
import subprocess
import uuid
from functools import lru_cache

logger = logging.getLogger(__name__)

_SUPPORTED_PLATFORMS = {"Windows", "Darwin"}


class HWIDError(Exception):
    """Raised when the hardware ID cannot be determined."""


# ── Platform-specific extractors ──────────────────────────────────────────────


def _get_hwid_windows() -> str:
    """Extract the motherboard UUID via WMI on Windows."""
    try:
        result = subprocess.run(
            ["wmic", "csproduct", "get", "UUID"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0:
            raise HWIDError(f"wmic exited with code {result.returncode}")

        lines = [
            line.strip()
            for line in result.stdout.splitlines()
            if line.strip() and line.strip().upper() != "UUID"
        ]
        if not lines:
            raise HWIDError("wmic returned empty UUID output")

        raw_uuid = lines[0]
        if raw_uuid.replace("-", "") == "F" * 32:
            raise HWIDError("wmic returned a nil/placeholder UUID")

        return raw_uuid.upper()

    except FileNotFoundError:
        logger.warning("wmic not found — attempting PowerShell fallback")
        return _get_hwid_windows_ps()
    except subprocess.TimeoutExpired as exc:
        raise HWIDError("wmic call timed out") from exc


def _get_hwid_windows_ps() -> str:
    """Fallback: PowerShell CIM query (Windows 11+ may deprecate wmic)."""
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "(Get-CimInstance Win32_ComputerSystemProduct).UUID",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        raw_uuid = result.stdout.strip()
        if not raw_uuid or result.returncode != 0:
            raise HWIDError("PowerShell UUID query returned empty result")
        return raw_uuid.upper()

    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise HWIDError(f"PowerShell fallback failed: {exc}") from exc


def _get_hwid_macos() -> str:
    """Extract IOPlatformUUID via ioreg on macOS."""
    try:
        result = subprocess.run(
            ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            raise HWIDError(f"ioreg exited with code {result.returncode}")

        for line in result.stdout.splitlines():
            if "IOPlatformUUID" in line:
                parts = line.split('"')
                # The UUID sits between the last pair of quotes:
                #   "IOPlatformUUID" = "XXXXXXXX-XXXX-..."
                uuid_candidates = [
                    p for p in parts if len(p) >= 32 and "-" in p
                ]
                if uuid_candidates:
                    return uuid_candidates[0].upper()

        raise HWIDError("IOPlatformUUID not found in ioreg output")

    except FileNotFoundError as exc:
        raise HWIDError("ioreg binary not found — unsupported macOS env") from exc
    except subprocess.TimeoutExpired as exc:
        raise HWIDError("ioreg call timed out") from exc


def _get_hwid_fallback() -> str:
    """
    Last-resort HWID: SHA-256 of hostname + MAC address.

    Less stable — changes if NIC or hostname changes — but guarantees
    the application can still start on unsupported platforms.
    """
    raw = f"{platform.node()}-{uuid.getnode()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:36].upper()


# ── Public API ────────────────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def get_hwid() -> str:
    """
    Return a unique, persistent hardware identifier for the current machine.

    The result is cached for the lifetime of the process so repeated calls
    are effectively free.

    Returns:
        Uppercase string identifier (UUID format on Win/Mac, SHA-256 slice
        on other platforms).

    Raises:
        HWIDError: If every extraction strategy fails.
    """
    system = platform.system()
    logger.debug("Detecting HWID on platform: %s", system)

    if system == "Windows":
        try:
            hwid = _get_hwid_windows()
            logger.info("HWID (Windows): %s", hwid)
            return hwid
        except HWIDError:
            logger.warning("Native Windows HWID extraction failed — using fallback")

    elif system == "Darwin":
        try:
            hwid = _get_hwid_macos()
            logger.info("HWID (macOS): %s", hwid)
            return hwid
        except HWIDError:
            logger.warning("Native macOS HWID extraction failed — using fallback")

    else:
        logger.warning("Unsupported platform '%s' — using fallback HWID", system)

    hwid = _get_hwid_fallback()
    logger.info("HWID (fallback): %s", hwid)
    return hwid
