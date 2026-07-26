"""Admin auth: Google OAuth login + session cookie + whitelist enforcement.

Public read endpoints never call these dependencies. Every mutating endpoint
depends on `require_admin`, so authorization is enforced server-side — the
frontend is never trusted.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from .config import get_settings
from .database import get_db
from .models import Admin

settings = get_settings()

SESSION_EMAIL_KEY = "admin_email"


def is_whitelisted(db: Session, email: str) -> bool:
    email = (email or "").strip().lower()
    if not email:
        return False
    if email in settings.admin_email_list:
        return True
    return db.query(Admin).filter(Admin.email == email).one_or_none() is not None


def ensure_bootstrap_admins(db: Session) -> None:
    """Seed the whitelist from ADMIN_EMAILS so the first admins can log in."""
    for email in settings.admin_email_list:
        existing = db.query(Admin).filter(Admin.email == email).one_or_none()
        if existing is None:
            db.add(Admin(email=email, added_by="ADMIN_EMAILS env"))
    db.commit()


def current_admin_email(request: Request) -> str | None:
    return request.session.get(SESSION_EMAIL_KEY)


def require_admin(request: Request, db: Session = Depends(get_db)) -> str:
    """Dependency for all mutating endpoints. Returns the admin email or 401/403."""
    email = current_admin_email(request)
    if not email:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Admin login required.")
    if not is_whitelisted(db, email):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Email is not an authorized admin.")
    return email
