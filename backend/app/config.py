"""Application settings, loaded from environment (.env supported)."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg2://badminton:badminton@localhost:5432/badminton"
    admin_emails: str = ""
    secret_key: str = "dev-insecure-secret-change-me"

    google_client_id: str = ""
    google_client_secret: str = ""
    oauth_redirect_uri: str = "http://localhost:8000/api/auth/callback"
    frontend_url: str = "http://localhost:5173"

    # DEV ONLY: when true, /api/auth/dev-login logs in as the first ADMIN_EMAILS
    # entry without Google. Never enable in production.
    allow_dev_login: bool = False

    @property
    def admin_email_list(self) -> list[str]:
        return [e.strip().lower() for e in self.admin_emails.split(",") if e.strip()]

    @property
    def oauth_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)


@lru_cache
def get_settings() -> Settings:
    return Settings()
