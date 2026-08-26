"""Application settings, loaded from environment (.env supported)."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg2://badminton:badminton@localhost:5432/badminton"
    secret_key: str = "dev-insecure-secret-change-me"

    # Shared admin access code. Anyone with this code can log in as an admin and
    # edit. Set a strong value in production.
    admin_access_code: str = "trials2026"

    frontend_url: str = "http://localhost:5173"

    @property
    def db_url(self) -> str:
        """Normalize provider-style 'postgres://' to SQLAlchemy's 'postgresql+psycopg2://'."""
        url = self.database_url
        if url.startswith("postgres://"):
            url = "postgresql+psycopg2://" + url[len("postgres://"):]
        elif url.startswith("postgresql://") and "+psycopg2" not in url:
            url = "postgresql+psycopg2://" + url[len("postgresql://"):]
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()
