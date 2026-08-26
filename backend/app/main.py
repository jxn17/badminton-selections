"""FastAPI application entrypoint."""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from .config import get_settings
from .database import Base, engine
from .routers import admin, auth_routes, public

settings = get_settings()

app = FastAPI(title="Badminton Trials 2026 — Draws", version="2.0.0")

# Signed session cookie for the admin login. https_only is fine behind TLS in prod;
# same_site lax works because the frontend proxies /api (same origin).
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    same_site="lax",
    https_only=settings.frontend_url.startswith("https"),
)
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
    # Schema is created on boot (no Alembic step needed for this event tool).
    Base.metadata.create_all(bind=engine)


# Serve the built frontend (single-origin deploy). In production the Docker image
# copies the Vite build into /app/static; the API routes above take precedence,
# and everything else falls back to the SPA's index.html.
_STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
if os.path.isdir(_STATIC_DIR):
    app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="static")
