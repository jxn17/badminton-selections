"""DATABASE_URL normalization for the async drivers.

Deployments already hold a URL in one of several spellings (Railway hands out
`postgres://`, docker-compose here used `postgresql+psycopg2://`), and asyncpg
rejects libpq-only query params like `sslmode` outright. None of those env vars
should have to change, so the normalizer has to absorb all of it.
"""
from __future__ import annotations

import pytest

from app.config import Settings


def _s(url: str) -> Settings:
    return Settings(database_url=url)


@pytest.mark.parametrize(
    "given",
    [
        "postgres://u:p@host:5432/db",
        "postgresql://u:p@host:5432/db",
        "postgresql+psycopg2://u:p@host:5432/db",
        "postgresql+psycopg://u:p@host:5432/db",
        "postgresql+asyncpg://u:p@host:5432/db",
    ],
)
def test_every_postgres_spelling_becomes_asyncpg(given):
    assert _s(given).db_url == "postgresql+asyncpg://u:p@host:5432/db"


def test_sqlite_becomes_aiosqlite():
    assert _s("sqlite:///./x.db").db_url == "sqlite+aiosqlite:///./x.db"
    # Already-async spelling is left alone.
    assert _s("sqlite+aiosqlite:///./x.db").db_url == "sqlite+aiosqlite:///./x.db"


def test_libpq_only_params_are_stripped_and_reported():
    s = _s("postgres://u:p@host/db?sslmode=require")
    assert s.db_url == "postgresql+asyncpg://u:p@host/db"
    assert s.db_ssl_required is True


def test_other_query_params_survive():
    s = _s("postgres://u:p@host/db?sslmode=require&application_name=trials")
    assert s.db_url == "postgresql+asyncpg://u:p@host/db?application_name=trials"


def test_plain_url_needs_no_ssl():
    assert _s("postgres://u:p@host/db").db_ssl_required is False
    assert _s("sqlite:///./x.db").db_ssl_required is False
