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
