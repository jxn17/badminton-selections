"""FastAPI application entrypoint."""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.middleware.sessions import SessionMiddleware

from .config import get_settings
from .database import Base, engine, ensure_incremental_migrations
from .routers import admin, auth_routes, public

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Schema is created on boot. Wait for the DB to be reachable first — Railway's
    # private networking (postgres.railway.internal) can be a few seconds slow on
    # first boot, so we retry instead of crashing (which would fail the healthcheck).
    # The sleep is asyncio's: even startup must not block the loop.
    last_err: Exception | None = None
    for attempt in range(1, 31):  # ~ up to 60s
        try:
            async with engine.begin() as conn:
                await conn.execute(text("SELECT 1"))
                await conn.run_sync(Base.metadata.create_all)
            await ensure_incremental_migrations(engine)
            print(f"[startup] DB ready (attempt {attempt}); schema ensured.", flush=True)
            break
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            print(f"[startup] DB not ready (attempt {attempt}): {exc}", flush=True)
            await asyncio.sleep(2)
    else:
        # Don't crash — start serving so /api/health passes and the error is visible.
        print(f"[startup] WARNING: DB never became reachable: {last_err}", flush=True)

    yield

    # Close the async connection pool cleanly so in-flight sockets aren't left
    # dangling on redeploy.
    await engine.dispose()


app = FastAPI(title="Badminton Trials 2026 — Draws", version="3.0.0", lifespan=lifespan)

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


# Serve the built frontend (single-origin deploy). In production the Docker image
# copies the Vite build into /app/static; the API routes above take precedence,
# and everything else falls back to the SPA's index.html.
_STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
if os.path.isdir(_STATIC_DIR):
    app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="static")
