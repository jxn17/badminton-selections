"""SQLAlchemy engine/session setup."""
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings

settings = get_settings()

# For SQLite (used by the test suite) we need check_same_thread=False.
if settings.db_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
    engine = create_engine(settings.db_url, connect_args=connect_args, future=True)
else:
    # NOTE: deliberately NOT using pool_pre_ping — it fires an extra "SELECT 1"
    # before every checkout, i.e. one wasted round-trip per request. Recycling
    # connections on a timer avoids stale sockets without that per-request cost.
    # A slightly larger pool keeps connections warm across concurrent admins.
    engine = create_engine(
        settings.db_url,
        connect_args={"connect_timeout": 10},
        pool_recycle=1800,
        pool_size=10,
        max_overflow=5,
        future=True,
    )
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a scoped DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_incremental_migrations(bind) -> None:
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
    with bind.begin() as conn:
        for stmt in statements:
            conn.execute(text(stmt))
