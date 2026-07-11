#!/usr/bin/env python3
"""Fail a release before deployment when commercial safety settings are incomplete."""

from __future__ import annotations

import json
import os
import sys
from urllib.parse import urlparse


def present(name: str) -> bool:
    value = os.getenv(name, "").strip()
    return bool(value and "replace_me" not in value.lower())


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []
    required = [
        "DATABASE_URL",
        "JWT_SECRET",
        "RELEASE_SHA",
        "BUILD_TIME",
        "R2_ACCOUNT_ID",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "R2_BUCKET_NAME",
        "BILLING_WEBHOOK_SECRET",
    ]
    for name in required:
        if not present(name):
            errors.append(f"{name} is missing or still a placeholder")
    if os.getenv("ENV") != "production":
        errors.append("ENV must equal production for a production release")
    if os.getenv("STORAGE_BACKEND") != "r2":
        errors.append("STORAGE_BACKEND must equal r2; local production fallback is forbidden")
    database_url = os.getenv("DATABASE_URL", "")
    if database_url:
        parsed = urlparse(database_url.replace("postgresql+asyncpg://", "postgresql://", 1))
        host = (parsed.hostname or "").lower()
        if host in {"localhost", "127.0.0.1", "postgres", "db"}:
            errors.append("Production database must be isolated from the application host")
        if "sslmode=" not in database_url and "ssl=" not in database_url:
            warnings.append("DATABASE_URL does not visibly declare TLS; confirm provider-enforced TLS")
    if len(os.getenv("JWT_SECRET", "")) < 32:
        errors.append("JWT_SECRET must contain at least 32 characters")
    if len(os.getenv("BILLING_WEBHOOK_SECRET", "")) < 24:
        errors.append("BILLING_WEBHOOK_SECRET is too short")
    if not os.getenv("PRIVACY_HASH_PEPPER"):
        warnings.append("PRIVACY_HASH_PEPPER is absent; JWT_SECRET fallback will be used")
    result = {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "release_sha": os.getenv("RELEASE_SHA"),
        "storage_backend": os.getenv("STORAGE_BACKEND"),
        "database_host": urlparse(database_url.replace("postgresql+asyncpg://", "postgresql://", 1)).hostname if database_url else None,
    }
    print(json.dumps(result, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
