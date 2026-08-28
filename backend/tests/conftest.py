"""Test fixtures. Uses a throwaway SQLite DB so tests need no Postgres.

The app is fully async now, so the session fixture is too — `asyncio_mode = auto`
in pytest.ini means test functions can just be `async def` with no marker.
"""
from __future__ import annotations

import os
import tempfile

# Must be set BEFORE importing app.database (engine is built from settings at import).
_TEST_DB = os.path.join(tempfile.gettempdir(), "badminton_test.db")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TEST_DB}"
os.environ["SECRET_KEY"] = "test-secret"
os.environ["ADMIN_EMAILS"] = "admin@test.dev"

import pytest_asyncio  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402


@pytest_asyncio.fixture()
async def db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
