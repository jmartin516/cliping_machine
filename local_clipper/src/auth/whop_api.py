"""
Whop API license-validation client.

Validates a user-supplied license key against the Whop platform, binding it
to the machine's Hardware ID (HWID) so a single key cannot be shared across
multiple devices.

The module is intentionally transport-agnostic: it returns typed dataclass
results so the GUI layer never handles raw HTTP responses.

Environment variables (loaded from .env):
    WHOP_API_URL  — Base validation endpoint.
    WHOP_API_KEY  — Bearer token for Whop API authentication.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

import requests
from dotenv import load_dotenv

from src.auth.hwid import HWIDError, get_hwid

logger = logging.getLogger(__name__)

# Load .env from project root (next to main.py)
_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(_ENV_PATH)

_API_URL: str = os.getenv("WHOP_API_URL", "https://api.whop.com/api/v2/memberships")
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

    # ── 2. Call Whop API ─────────────────────────────────────────────────
    payload = {
        "license_key": license_key,
        "metadata": {"hwid": hwid},
    }
    headers = {
        "Authorization": f"Bearer {_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    logger.debug("Validating license against %s", _API_URL)

    try:
        response = requests.post(
            _API_URL,
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
    """Map HTTP status codes and Whop payload to a typed result."""

    if response.status_code == 200:
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

        if bound_hwid and bound_hwid != hwid:
            return ValidationFailure(
                error_code=_ERR_HWID_MISMATCH,
                message="This license is already activated on another machine.",
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
