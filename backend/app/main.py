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
    # Schema is created on boot. Wait for the DB to be reachable first — Railway's
    # private networking (postgres.railway.internal) can be a few seconds slow on
    # first boot, so we retry instead of crashing (which would fail the healthcheck).
    import time

    from sqlalchemy import text

    last_err: Exception | None = None
    for attempt in range(1, 31):  # ~ up to 60s
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            Base.metadata.create_all(bind=engine)
            # Lightweight migrations for columns added after first deploy.
            if not settings.db_url.startswith("sqlite"):
                with engine.connect() as conn:
                    conn.execute(text(
                        "ALTER TABLE players ADD COLUMN IF NOT EXISTS no_show BOOLEAN NOT NULL DEFAULT FALSE"
                    ))
                    conn.execute(text(
                        "ALTER TABLE players ADD COLUMN IF NOT EXISTS reported BOOLEAN NOT NULL DEFAULT FALSE"
                    ))
                    conn.execute(text(
                        "ALTER TABLE round_formats ADD COLUMN IF NOT EXISTS alt_points_to_win INTEGER"
                    ))
                    # Backfill: set alt=11 on existing rows that have primary=21 so
                    # dual-target scoring works out of the box.
                    conn.execute(text(
                        "UPDATE round_formats SET alt_points_to_win = 11 "
                        "WHERE alt_points_to_win IS NULL AND points_to_win = 21"
                    ))
                    conn.commit()
            print(f"[startup] DB ready (attempt {attempt}); schema ensured.", flush=True)
            return
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            print(f"[startup] DB not ready (attempt {attempt}): {exc}", flush=True)
            time.sleep(2)
    # Don't crash — start serving so /api/health passes and the error is visible.
    print(f"[startup] WARNING: DB never became reachable: {last_err}", flush=True)


# Serve the built frontend (single-origin deploy). In production the Docker image
# copies the Vite build into /app/static; the API routes above take precedence,
# and everything else falls back to the SPA's index.html.
_STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
if os.path.isdir(_STATIC_DIR):
    app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="static")
