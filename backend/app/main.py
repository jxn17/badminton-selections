"""FastAPI application entrypoint."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from .auth import ensure_bootstrap_admins
from .config import get_settings
from .database import Base, SessionLocal, engine
from .routers import admin, auth_routes, public

settings = get_settings()

app = FastAPI(title="College Badminton Selection Draws", version="1.0.0")

# Signed session cookie for the admin login.
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, same_site="lax")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(public.router)
app.include_router(auth_routes.router)
app.include_router(admin.router)


@app.on_event("startup")
def on_startup() -> None:
    # In production, prefer Alembic migrations (`alembic upgrade head`). create_all
    # is a convenience so the app also boots on a fresh DB without a migration step.
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        ensure_bootstrap_admins(db)
    finally:
        db.close()


@app.get("/api/health")
def health():
    return {"status": "ok"}
