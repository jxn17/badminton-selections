"""Test fixtures. Uses a throwaway SQLite DB so tests need no Postgres."""
from __future__ import annotations

import os
import tempfile

# Must be set BEFORE importing app.database (engine is built from settings at import).
_TEST_DB = os.path.join(tempfile.gettempdir(), "badminton_test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB}"
os.environ["SECRET_KEY"] = "test-secret"
os.environ["ADMIN_EMAILS"] = "admin@test.dev"

import pytest  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402


@pytest.fixture()
def db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
