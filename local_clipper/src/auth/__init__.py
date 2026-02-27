"""Authentication and license management module."""

from .license_storage import save_license, load_license, clear_license
from .whop_api import validate_license, ValidationSuccess, ValidationFailure
from .hwid import get_hwid, HWIDError

__all__ = [
    'save_license',
    'load_license',
    'clear_license',
    'validate_license',
    'ValidationSuccess',
    'ValidationFailure',
    'get_hwid',
    'HWIDError',
]
