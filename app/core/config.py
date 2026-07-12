"""Application settings — loaded from environment variables on startup."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    ENV: Literal["development", "staging", "production"] = "development"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    RELEASE_SHA: str = ""
    BUILD_TIME: str = ""
    SCHEMA_VERSION: str = "0018"
    RENDERER_VERSION: str = "phase1-renderer"
    PROMPT_BUNDLE_VERSION: str = "phase3-prompts"
    CANONICAL_SCHEMA_VERSION: str = "1"

    DATABASE_URL: str = Field(..., description="Async Postgres URL")

    JWT_SECRET: str = Field(..., min_length=32)
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRY_DAYS: int = 30
    MAGIC_LINK_EXPIRY_MINUTES: int = 15
    SESSION_IDLE_MINUTES: int = 720
    SESSION_ABSOLUTE_DAYS: int = 30
    SESSION_REAUTH_MINUTES: int = 15
    SESSION_COOKIE_NAME: str = "access_token"
    DEFAULT_INSTITUTION_SHORT_NAME: str = "MCC"

    FRONTEND_URL: str = "http://localhost:3000"
    FRONTEND_LOGIN_PATH: str = "/auth/callback"

    ANTHROPIC_API_KEY: str = Field(..., min_length=10)
    GOOGLE_CLIENT_ID: str = ""
    CLAUDE_CLI_PATH: str = "claude"
    CLAUDE_COACHING_MODEL: str = "claude-sonnet-4-6"
    CLAUDE_COMPILE_MODEL: str = "claude-opus-4-8"
    CLAUDE_UTILITY_MODEL: str = "claude-haiku-4-5-20251001"
    AI_PROVIDER_FAILURE_THRESHOLD: int = 5
    AI_CIRCUIT_COOLDOWN_SECONDS: int = 300
    AI_GLOBAL_EMERGENCY_THROTTLE: bool = False
    USER_MONTHLY_INPUT_TOKEN_CAP: int = 2_000_000
    USER_MONTHLY_OUTPUT_TOKEN_CAP: int = 200_000

    JOB_LEASE_SECONDS: int = 120
    JOB_HEARTBEAT_SECONDS: int = 20
    WORKER_QUEUE: str = "general"
    WORKER_ID: str = ""

    BILLING_PROVIDER: str = "manual"
    BILLING_WEBHOOK_SECRET: str = ""
    BILLING_WEBHOOK_TOLERANCE_SECONDS: int = 300
    BILLING_GRACE_DAYS: int = 7

    RESEND_API_KEY: str = ""
    EMAIL_FROM_ADDRESS: str = "thesis@robofox.online"
    EMAIL_FROM_NAME: str = "Robofox Thesis Studio"

    LOCAL_STORAGE_DIR: str = "var/storage"
    STORAGE_BACKEND: Literal["auto", "r2", "local"] = "auto"
    PRODUCTION_REQUIRE_R2: bool = True
    R2_ACCOUNT_ID: str = ""
    R2_ACCESS_KEY_ID: str = ""
    R2_SECRET_ACCESS_KEY: str = ""
    R2_BUCKET_NAME: str = "thesis-studio"
    R2_PUBLIC_URL: str = ""

    MALWARE_SCAN_MODE: Literal["disabled", "clamav"] = "disabled"
    PRODUCTION_REQUIRE_MALWARE_SCAN: bool = True
    CLAMAV_HOST: str = "clamav"
    CLAMAV_PORT: int = 3310
    CLAMAV_TIMEOUT_SECONDS: float = 30.0

    SUPPORT_ACCESS_DEFAULT_MINUTES: int = 60
    DELETION_GRACE_DAYS: int = 30
    PRIVACY_HASH_PEPPER: str = ""
    CORS_ORIGINS: str = "http://localhost:3000"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def magic_link_url_template(self) -> str:
        return f"{self.FRONTEND_URL.rstrip('/')}{self.FRONTEND_LOGIN_PATH}?token={{token}}"

    @property
    def effective_privacy_hash_pepper(self) -> str:
        return self.PRIVACY_HASH_PEPPER or self.JWT_SECRET

    @field_validator("JWT_SECRET")
    @classmethod
    def jwt_secret_not_default(cls, value: str) -> str:
        if "replace_me" in value.lower():
            raise ValueError("JWT_SECRET is still the placeholder")
        return value

    @field_validator("RELEASE_SHA")
    @classmethod
    def release_sha_shape(cls, value: str) -> str:
        if value and (len(value) < 7 or len(value) > 64):
            raise ValueError("RELEASE_SHA must be an abbreviated or full commit SHA")
        return value

    @model_validator(mode="after")
    def production_safety(self) -> "Settings":
        if self.ENV == "production":
            if self.DEBUG:
                raise ValueError("DEBUG must be false in production")
            if self.PRODUCTION_REQUIRE_R2 and self.STORAGE_BACKEND != "r2":
                raise ValueError("Production requires STORAGE_BACKEND=r2")
            missing_r2 = [
                name
                for name, value in {
                    "R2_ACCOUNT_ID": self.R2_ACCOUNT_ID,
                    "R2_ACCESS_KEY_ID": self.R2_ACCESS_KEY_ID,
                    "R2_SECRET_ACCESS_KEY": self.R2_SECRET_ACCESS_KEY,
                    "R2_BUCKET_NAME": self.R2_BUCKET_NAME,
                }.items()
                if not value or "replace_me" in value.lower()
            ]
            if self.PRODUCTION_REQUIRE_R2 and missing_r2:
                raise ValueError(f"Production R2 configuration is incomplete: {', '.join(missing_r2)}")
            if not self.RELEASE_SHA:
                raise ValueError("Production deployments must provide RELEASE_SHA")
            if self.SESSION_IDLE_MINUTES <= 0 or self.SESSION_ABSOLUTE_DAYS <= 0:
                raise ValueError("Production session lifetimes must be positive")
            if self.PRODUCTION_REQUIRE_MALWARE_SCAN and self.MALWARE_SCAN_MODE != "clamav":
                raise ValueError("Production requires MALWARE_SCAN_MODE=clamav")
            if self.MALWARE_SCAN_MODE == "clamav" and not self.CLAMAV_HOST.strip():
                raise ValueError("CLAMAV_HOST is required when malware scanning is enabled")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
