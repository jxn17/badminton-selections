"""SQLAlchemy **async** engine/session setup.

Every query in this app goes through `AsyncSession` on top of an asyncio driver
(asyncpg for Postgres, aiosqlite for SQLite), so no database round-trip ever
blocks the FastAPI event loop. Under load that is the difference between one
slow query stalling every concurrent visitor and it stalling only its own
request.
"""
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from .config import get_settings

settings = get_settings()

if settings.db_url.startswith("sqlite"):
    # aiosqlite: the test suite and local scratch DBs.
    engine: AsyncEngine = create_async_engine(
        settings.db_url,
        connect_args={"check_same_thread": False},
    )
else:
    # NOTE: deliberately NOT using pool_pre_ping — it fires an extra "SELECT 1"
    # before every checkout, i.e. one wasted round-trip per request. Recycling
    # connections on a timer avoids stale sockets without that per-request cost.
    # A slightly larger pool keeps connections warm across concurrent admins.
    #
    # asyncpg names its connect timeout `timeout` (not psycopg2's
    # `connect_timeout`), and takes TLS via `ssl` rather than a `sslmode` query
    # param — config.py strips that param out of the URL for us.
    connect_args: dict = {"timeout": 10}
    if settings.db_ssl_required:
        connect_args["ssl"] = True
    engine = create_async_engine(
        settings.db_url,
        connect_args=connect_args,
        pool_recycle=1800,
        pool_size=10,
        max_overflow=5,
    )

# expire_on_commit=False matters more under async than it did under sync: an
# expired attribute would otherwise lazy-refresh on plain attribute access,
# which is exactly the blocking-IO-outside-await that asyncio forbids. Handlers
# that return an object after commit (e.g. the score snapshot) rely on this.
SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    autoflush=False,
    expire_on_commit=False,
)


class Base(AsyncAttrs, DeclarativeBase):
    """AsyncAttrs gives every model `await obj.awaitable_attrs.<relationship>`,
    the supported way to pull an un-loaded relationship inside async code."""


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a per-request async DB session."""
    async with SessionLocal() as db:
        yield db


async def ensure_incremental_migrations(bind: AsyncEngine) -> None:
    """Add columns introduced after the app first went live.

    There's no Alembic here, and Base.metadata.create_all() only creates tables
    that don't exist yet — it never alters an existing table. On a live Postgres
    (with real tournament data already in it) that means a new column on an
    existing model needs an explicit, additive ALTER TABLE. This is intentionally
    tiny and append-only: every statement is idempotent (IF NOT EXISTS) and never
    drops or rewrites data. SQLite (tests/local scratch DBs) is always created
    fresh via create_all, which already includes new columns, so it's skipped.
    """
    if bind.dialect.name != "postgresql":
        return
    from sqlalchemy import text

    statements = [
        "ALTER TABLE players ADD COLUMN IF NOT EXISTS reported BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE matches ADD COLUMN IF NOT EXISTS no_show_player_id INTEGER REFERENCES players(id)",
    ]
    async with bind.begin() as conn:
        for stmt in statements:
            await conn.execute(text(stmt))
