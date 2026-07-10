"""Application settings — loaded from environment variables on startup."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration. All values come from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ---- Application ----
    ENV: Literal["development", "staging", "production"] = "development"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    # ---- Database ----
    DATABASE_URL: str = Field(
        ...,
        description="Async Postgres URL (postgresql+asyncpg://...)",
    )

    # ---- Auth ----
    JWT_SECRET: str = Field(..., min_length=32)
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRY_DAYS: int = 30
    MAGIC_LINK_EXPIRY_MINUTES: int = 15

    # Open signup: any email domain may sign up. Domain matching against an
    # institution's email_domains is a hint; this is the fallback institution
    # for emails that don't match any (gmail, protonmail, etc.).
    DEFAULT_INSTITUTION_SHORT_NAME: str = "MCC"

    # ---- Frontend ----
    FRONTEND_URL: str = "http://localhost:3000"
    FRONTEND_LOGIN_PATH: str = "/auth/callback"

    # ---- Anthropic ----
    # ANTHROPIC_API_KEY is unused under the Max+CLI auth path. Kept non-empty so
    # the Settings model's min_length check passes; .env has a placeholder.
    ANTHROPIC_API_KEY: str = Field(..., min_length=10)
    CLAUDE_CLI_PATH: str = "claude"
    CLAUDE_COACHING_MODEL: str = "claude-sonnet-4-6"
    CLAUDE_COMPILE_MODEL: str = "claude-opus-4-8"
    CLAUDE_UTILITY_MODEL: str = "claude-haiku-4-5-20251001"

    USER_MONTHLY_INPUT_TOKEN_CAP: int = 2_000_000
    USER_MONTHLY_OUTPUT_TOKEN_CAP: int = 200_000

    # ---- Email ----
    RESEND_API_KEY: str = ""
    EMAIL_FROM_ADDRESS: str = "thesis@robofox.online"
    EMAIL_FROM_NAME: str = "Robofox Thesis Studio"

    # ---- Storage ----
    LOCAL_STORAGE_DIR: str = "var/storage"
    STORAGE_BACKEND: str = "auto"  # "auto" | "r2" | "local"

    # ---- R2 ----
    R2_ACCOUNT_ID: str = ""
    R2_ACCESS_KEY_ID: str = ""
    R2_SECRET_ACCESS_KEY: str = ""
    R2_BUCKET_NAME: str = "thesis-studio"
    R2_PUBLIC_URL: str = ""

    # ---- CORS ----
    CORS_ORIGINS: str = "http://localhost:3000"

    # ---- Computed ----
    @property
    def cors_origins_list(self) -> list[str]:
        """Parsed list of CORS allowed origins."""
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def magic_link_url_template(self) -> str:
        """Template for magic-link URLs sent in email."""
        return f"{self.FRONTEND_URL.rstrip('/')}{self.FRONTEND_LOGIN_PATH}?token={{token}}"

    @field_validator("JWT_SECRET")
    @classmethod
    def jwt_secret_not_default(cls, v: str) -> str:
        """Refuse to boot with the placeholder secret from .env.example."""
        if "replace_me" in v.lower():
            raise ValueError(
                "JWT_SECRET is still the placeholder. "
                "Generate one with: openssl rand -hex 32"
            )
        return v


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance. Use this everywhere instead of constructing Settings()."""
    return Settings()
