"""Typed settings loaded from the environment (and the repo-root .env in local dev)."""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    database_url: str = "postgresql+psycopg://instructor:instructor@localhost:5432/instructor"
    redis_url: str = "redis://localhost:6379/0"

    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-sonnet-5-5"
    # Per request. The SDK retries 429/5xx twice on top of this.
    anthropic_timeout_seconds: float = 90

    session_ttl_seconds: int = 8 * 60 * 60
    # Secure cookies need HTTPS; local dev is plain http, so this is off unless deployed.
    cookie_secure: bool = False
    dashboard_ttl_seconds: int = 10 * 60


@lru_cache
def get_settings() -> Settings:
    return Settings()
