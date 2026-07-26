"""Google OAuth login/logout + session status."""
from __future__ import annotations

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..auth import SESSION_EMAIL_KEY, current_admin_email, is_whitelisted
from ..config import get_settings
from ..database import get_db

settings = get_settings()
router = APIRouter(prefix="/api/auth", tags=["auth"])

oauth = OAuth()
if settings.oauth_configured:
    oauth.register(
        name="google",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )


@router.get("/login")
async def login(request: Request):
    if not settings.oauth_configured:
        raise HTTPException(503, "Google OAuth is not configured (set GOOGLE_CLIENT_ID/SECRET).")
    return await oauth.google.authorize_redirect(request, settings.oauth_redirect_uri)


@router.get("/callback")
async def callback(request: Request, db: Session = Depends(get_db)):
    if not settings.oauth_configured:
        raise HTTPException(503, "Google OAuth is not configured.")
    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception as exc:  # noqa: BLE001 - surface a clean message to the user
        raise HTTPException(400, f"OAuth failed: {exc}") from exc

    userinfo = token.get("userinfo") or {}
    email = (userinfo.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(400, "Google did not return an email.")

    # Store the session regardless; require_admin re-checks the whitelist on every
    # mutating call, but we reject non-admins here for a clean UX.
    if not is_whitelisted(db, email):
        return RedirectResponse(f"{settings.frontend_url}/admin?error=not_authorized")

    request.session[SESSION_EMAIL_KEY] = email
    return RedirectResponse(f"{settings.frontend_url}/admin")


@router.post("/dev-login")
async def dev_login(request: Request, db: Session = Depends(get_db)):
    """DEV ONLY. Enabled by ALLOW_DEV_LOGIN=true. Logs in as the first admin email."""
    if not settings.allow_dev_login:
        raise HTTPException(404, "Not found.")
    if not settings.admin_email_list:
        raise HTTPException(400, "Set ADMIN_EMAILS to use dev login.")
    email = settings.admin_email_list[0]
    if not is_whitelisted(db, email):
        raise HTTPException(403, "Configured dev email is not whitelisted.")
    request.session[SESSION_EMAIL_KEY] = email
    return {"ok": True, "email": email}


@router.post("/logout")
async def logout(request: Request):
    request.session.pop(SESSION_EMAIL_KEY, None)
    return {"ok": True}


@router.get("/me")
async def me(request: Request, db: Session = Depends(get_db)):
    email = current_admin_email(request)
    if not email:
        return {"authenticated": False, "email": None, "is_admin": False}
    return {"authenticated": True, "email": email, "is_admin": is_whitelisted(db, email)}
