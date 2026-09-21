"""Application settings. Everything configurable lives here and comes from the environment."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = REPO_ROOT / "backend"
CONFIG_DIR = REPO_ROOT / "config"


class Settings(BaseSettings):
    """Read once at start-up. See .env.example for the full list."""

    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        env_nested_delimiter="__",
    )

    # --- core -----------------------------------------------------------------
    env: Literal["dev", "test", "prod"] = "dev"
    app_url: str = "http://localhost:3000"
    api_url: str = "http://localhost:8000"
    log_level: str = "info"
    session_secret: str = "dev-secret-change-me"

    # --- database -------------------------------------------------------------
    database_url: str = "postgresql+asyncpg://knori:knori@localhost:55432/knori"

    # --- LLM ------------------------------------------------------------------
    llm_mode: Literal["fake", "live"] = "fake"
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    openai_reasoning_model: str = "gpt-5.6-sol"
    openai_background_model: str = "gpt-5.6-terra"
    debug_payloads: bool = False

    # --- jobs -----------------------------------------------------------------
    worker_concurrency: int = 4
    knori_dev_now: str = ""

    # --- signup ---------------------------------------------------------------
    signup_mode: Literal["invite", "open"] = "invite"
    first_invite_code: str = "KNORI-DEV"

    # --- email ----------------------------------------------------------------
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "KnoRI <hello@knori.local>"
    smtp_tls: bool = False

    # --- backups (VPS only) ---------------------------------------------------
    s3_endpoint: str = ""
    s3_bucket: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    backup_key: str = ""

    # --- optional -------------------------------------------------------------
    sentry_dsn: str = ""

    # --- derived --------------------------------------------------------------
    config_dir: Path = Field(default=CONFIG_DIR)

    @field_validator("log_level")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.lower()

    @property
    def is_dev(self) -> bool:
        return self.env == "dev"

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"

    @property
    def cookie_secure(self) -> bool:
        """Cookies are Secure everywhere except plain-http local development."""
        return not self.api_url.startswith("http://")

    def sync_database_url(self) -> str:
        """psycopg-style URL, used by tooling that cannot speak asyncpg."""
        return self.database_url.replace("+asyncpg", "")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
