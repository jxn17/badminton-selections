"""Admin auth via a shared access code.

Anyone with the code logs in as an admin and may edit. Each admin also supplies
a display name (for audit attribution). Public read endpoints never call these;
every mutating endpoint depends on `require_admin`, enforced server-side.
"""
from __future__ import annotations

import hmac

from fastapi import HTTPException, Request, status

from .config import get_settings

settings = get_settings()

SESSION_ADMIN_KEY = "is_admin"
SESSION_NAME_KEY = "admin_name"


def code_is_valid(code: str) -> bool:
    expected = settings.admin_access_code or ""
    if not expected:
        return False
    return hmac.compare_digest((code or "").strip(), expected)


def current_admin_name(request: Request) -> str | None:
    if request.session.get(SESSION_ADMIN_KEY):
        return request.session.get(SESSION_NAME_KEY) or "admin"
    return None


def require_admin(request: Request) -> str:
    """Dependency for all mutating endpoints. Returns the admin's display name."""
    if not request.session.get(SESSION_ADMIN_KEY):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Admin login required.")
    return request.session.get(SESSION_NAME_KEY) or "admin"
