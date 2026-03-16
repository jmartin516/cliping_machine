"""
Whop API license-validation client.

Validates a user-supplied license key against the Whop platform, binding it
to the machine's Hardware ID (HWID) so a single key cannot be shared across
multiple devices.

Uses Whop API v2: POST /v2/memberships/{license_key}/validate_license
with metadata containing the HWID.

Environment variables (loaded from .env):
    WHOP_API_BASE  — Base URL (default: https://api.whop.com/api/v2).
    WHOP_API_KEY  — Bearer token for Whop API authentication.
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union
from urllib.parse import quote

import requests
from dotenv import load_dotenv

from src.auth.hwid import HWIDError, get_hwid
from src.utils.paths import get_env_path

logger = logging.getLogger(__name__)

# Load .env from project root (or PyInstaller bundle root)
_env_path = get_env_path()
load_dotenv(_env_path)
# Fallback: also try loading from cwd (bundled app may extract to temp)
if not _env_path.exists() and getattr(sys, "frozen", False):
    for _p in [Path.cwd() / ".env", Path(sys.executable).parent / ".env"]:
        if _p.exists():
            load_dotenv(_p)
            break

# Support WHOP_API_BASE (preferred) or legacy WHOP_API_URL
_api_base = os.getenv("WHOP_API_BASE", "").rstrip("/")
_api_url = os.getenv("WHOP_API_URL", "").rstrip("/")
if _api_base:
    _API_BASE = _api_base
elif _api_url:
    # Legacy: WHOP_API_URL was .../memberships → derive base
    _API_BASE = _api_url.removesuffix("/memberships") or "https://api.whop.com/api/v2"
else:
    _API_BASE = "https://api.whop.com/api/v2"
_API_KEY: str = os.getenv("WHOP_API_KEY", "")

_REQUEST_TIMEOUT_S = 15


# ── Result types ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ValidationSuccess:
    """Returned when the license is valid and bound to this HWID."""

    license_key: str
    hwid: str
    message: str = "License activated successfully."


@dataclass(frozen=True)
class ValidationFailure:
    """Returned when validation is rejected or an error occurs."""

    error_code: str
    message: str
    recoverable: bool = True


ValidationResult = Union[ValidationSuccess, ValidationFailure]


# ── Error taxonomy ────────────────────────────────────────────────────────────

_ERR_HWID = "HWID_ERROR"
_ERR_NETWORK = "NETWORK_ERROR"
_ERR_TIMEOUT = "TIMEOUT_ERROR"
_ERR_SERVER = "SERVER_ERROR"
_ERR_INVALID_KEY = "INVALID_KEY"
_ERR_HWID_MISMATCH = "HWID_MISMATCH"
_ERR_EXPIRED = "LICENSE_EXPIRED"
_ERR_UNKNOWN = "UNKNOWN_ERROR"
_ERR_CONFIG = "CONFIG_ERROR"


# ── Public API ────────────────────────────────────────────────────────────────


def validate_license(license_key: str) -> ValidationResult:
    """
    Validate *license_key* against the Whop API, binding it to this machine.

    Flow:
        1. Obtain HWID (fail fast if unavailable).
        2. POST the key + HWID to the configured Whop endpoint.
        3. Interpret the response and return a typed result.

    Args:
        license_key: The activation key entered by the user.

    Returns:
        ``ValidationSuccess`` on approval, ``ValidationFailure`` otherwise.
        The caller should never need to catch exceptions from this function.
    """
    license_key = license_key.strip()
    if not license_key:
        return ValidationFailure(
            error_code=_ERR_INVALID_KEY,
            message="License key cannot be empty.",
        )

    # Admin bypass: ADMIN_LICENSE_KEY puede ser una clave o varias separadas por coma
    admin_raw = os.getenv("ADMIN_LICENSE_KEY", "").strip()
    admin_keys = [k.strip() for k in admin_raw.split(",") if k.strip()]
    if admin_keys and license_key in admin_keys:
        try:
            hwid = get_hwid()
        except HWIDError:
            hwid = "admin"
        logger.info("Admin license accepted (bypass)")
        return ValidationSuccess(license_key=license_key, hwid=hwid)

    if not _API_KEY:
        logger.error("WHOP_API_KEY is not configured")
        return ValidationFailure(
            error_code=_ERR_CONFIG,
            message="Server configuration error. Contact support.",
            recoverable=False,
        )

    # ── 1. Resolve HWID ──────────────────────────────────────────────────
    try:
        hwid = get_hwid()
    except HWIDError as exc:
        logger.error("HWID extraction failed: %s", exc)
        return ValidationFailure(
            error_code=_ERR_HWID,
            message="Could not determine hardware ID. Try running as admin.",
        )

    # ── 2. Call Whop API v2 validate_license ─────────────────────────────
    # Endpoint: POST /v2/memberships/{license_key}/validate_license
    # Body: {"metadata": {"hwid": "..."}}
    url = f"{_API_BASE}/memberships/{quote(license_key)}/validate_license"
    payload = {"metadata": {"hwid": hwid}}
    headers = {
        "Authorization": f"Bearer {_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    logger.debug("Validating license against %s", url)

    try:
        response = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=_REQUEST_TIMEOUT_S,
        )
    except requests.ConnectionError as exc:
        logger.error("Connection error: %s", exc)
        return ValidationFailure(
            error_code=_ERR_NETWORK,
            message="Unable to reach the license server. Check your internet connection.",
        )
    except requests.Timeout as exc:
        logger.error("Request timed out: %s", exc)
        return ValidationFailure(
            error_code=_ERR_TIMEOUT,
            message="License server did not respond in time. Please retry.",
        )
    except requests.RequestException as exc:
        logger.error("Unexpected request error: %s", exc)
        return ValidationFailure(
            error_code=_ERR_UNKNOWN,
            message=f"Network error: {exc}",
        )

    # ── 3. Interpret response ────────────────────────────────────────────
    return _parse_response(response, license_key, hwid)


# ── Internal helpers ──────────────────────────────────────────────────────────


def _parse_response(
    response: requests.Response,
    license_key: str,
    hwid: str,
) -> ValidationResult:
    """Map HTTP status codes and Whop payload to a typed result.
    Whop API v2 returns 201 on successful validation."""
    # 200 and 201 both indicate success (some Whop versions may return 200)
    if response.status_code in (200, 201):
        try:
            data = response.json()
        except ValueError:
            return ValidationFailure(
                error_code=_ERR_SERVER,
                message="Received malformed response from license server.",
            )

        bound_hwid: Optional[str] = (
            data.get("metadata", {}).get("hwid")
            if isinstance(data.get("metadata"), dict)
            else None
        )

        # Whop can be inconsistent with metadata. If no bound_hwid, it's first activation — OK.
        if not bound_hwid:
            return ValidationSuccess(license_key=license_key, hwid=hwid)

        if bound_hwid != hwid:
            return ValidationFailure(
                error_code=_ERR_HWID_MISMATCH,
                message="This license is already activated on another device.",
                recoverable=False,
            )

        return ValidationSuccess(license_key=license_key, hwid=hwid)

    if response.status_code == 401:
        return ValidationFailure(
            error_code=_ERR_INVALID_KEY,
            message="Invalid or unrecognized license key.",
        )

    if response.status_code == 403:
        return ValidationFailure(
            error_code=_ERR_EXPIRED,
            message="License has expired or been revoked.",
            recoverable=False,
        )

    if response.status_code == 429:
        return ValidationFailure(
            error_code=_ERR_NETWORK,
            message="Too many attempts. Please wait a moment and try again.",
        )

    if 500 <= response.status_code < 600:
        logger.error("Server error %d: %s", response.status_code, response.text[:200])
        return ValidationFailure(
            error_code=_ERR_SERVER,
            message="License server is experiencing issues. Please try again later.",
        )

    logger.warning("Unhandled HTTP %d from Whop API", response.status_code)
    return ValidationFailure(
        error_code=_ERR_UNKNOWN,
        message=f"Unexpected server response (HTTP {response.status_code}).",
    )
