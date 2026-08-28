"""Application settings, loaded from environment (.env supported)."""
from functools import lru_cache
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic_settings import BaseSettings, SettingsConfigDict

# Query params that psycopg2/libpq understands but asyncpg does not. They are
# stripped from the URL and re-expressed as connect_args (see database.py), so
# an existing provider-issued DATABASE_URL keeps working unchanged.
_LIBPQ_ONLY_PARAMS = {"sslmode", "target_session_attrs", "channel_binding", "gssencmode"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://badminton:badminton@localhost:5432/badminton"
    secret_key: str = "dev-insecure-secret-change-me"

    # Shared admin access code. Anyone with this code can log in as an admin and
    # edit. Set a strong value in production.
    admin_access_code: str = "trials2026"

    frontend_url: str = "http://localhost:5173"

    # Seconds the public bracket/draws responses may be served from memory.
    # Any admin write busts the cache immediately, so this only ever delays
    # *unchanged* data (see app/cache.py).
    public_cache_ttl: int = 45

    @property
    def _split_db_url(self) -> tuple[str, dict[str, str]]:
        """Normalize the URL to an async driver and split off libpq-only params.

        Everything the app talks to is now driven by an asyncio driver:
        Postgres via asyncpg, SQLite (tests/local scratch) via aiosqlite. All the
        historical spellings are accepted so no deployment env var has to change:
        'postgres://', 'postgresql://', 'postgresql+psycopg2://'.
        """
        url = self.database_url
        for prefix in ("postgresql+psycopg2://", "postgresql+psycopg://", "postgresql://", "postgres://"):
            if url.startswith(prefix):
                url = "postgresql+asyncpg://" + url[len(prefix):]
                break
        else:
            if url.startswith("sqlite://") and "+aiosqlite" not in url:
                url = "sqlite+aiosqlite://" + url[len("sqlite://"):]

        if not url.startswith("postgresql+asyncpg://"):
            return url, {}

        # asyncpg rejects unknown query params outright, so pull them out.
        parts = urlsplit(url)
        kept: list[tuple[str, str]] = []
        stripped: dict[str, str] = {}
        for key, value in parse_qsl(parts.query, keep_blank_values=True):
            if key in _LIBPQ_ONLY_PARAMS:
                stripped[key] = value
            else:
                kept.append((key, value))
        return urlunsplit(parts._replace(query=urlencode(kept))), stripped

    @property
    def db_url(self) -> str:
        """SQLAlchemy async URL (asyncpg / aiosqlite), libpq-only params removed."""
        return self._split_db_url[0]

    @property
    def db_ssl_required(self) -> bool:
        """True when the original URL asked libpq for TLS (sslmode=require etc.)."""
        return self._split_db_url[1].get("sslmode", "").lower() in {
            "require", "verify-ca", "verify-full", "prefer",
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
