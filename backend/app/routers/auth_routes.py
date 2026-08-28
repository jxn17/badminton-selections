"""Shared access-code login + session status."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ..auth import SESSION_ADMIN_KEY, SESSION_NAME_KEY, code_is_valid, current_admin_name
from ..schemas import CodeLoginIn

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/code-login")
async def code_login(body: CodeLoginIn, request: Request):
    if not code_is_valid(body.code):
        raise HTTPException(401, "Incorrect access code.")
    request.session[SESSION_ADMIN_KEY] = True
    request.session[SESSION_NAME_KEY] = (body.name or "admin").strip()[:60] or "admin"
    return {"ok": True, "name": request.session[SESSION_NAME_KEY]}


@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@router.get("/me")
async def me(request: Request):
    name = current_admin_name(request)
    return {"is_admin": name is not None, "name": name}
