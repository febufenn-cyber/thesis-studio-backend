#!/usr/bin/env python3
"""Fail a release before deployment when safety settings are incomplete.

This verifier checks configuration evidence only. It does not claim that an
external provider, backup, legal review, or penetration test has succeeded.
Smoke tests and retained drill evidence remain separate release gates.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse


def present(name: str) -> bool:
    value = os.getenv(name, "").strip()
    return bool(value and "replace_me" not in value.lower())


def truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--target",
        choices=("staging", "production"),
        default=os.getenv("ENV", "staging"),
    )
    args = parser.parse_args()
    target = args.target
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
        "RESEND_API_KEY",
        "PRIVACY_HASH_PEPPER",
    ]
    for name in required:
        if not present(name):
            errors.append(f"{name} is missing or still a placeholder")

    configured_env = os.getenv("ENV", "").strip()
    if configured_env != target:
        errors.append(f"ENV must equal requested target {target!r}")
    if os.getenv("STORAGE_BACKEND") != "r2":
        errors.append("STORAGE_BACKEND must equal r2; release storage fallback is forbidden")
    if truthy("DEBUG"):
        errors.append("DEBUG must be false outside development")

    database_url = os.getenv("DATABASE_URL", "")
    database_host = None
    if database_url:
        parsed = urlparse(database_url.replace("postgresql+asyncpg://", "postgresql://", 1))
        database_host = (parsed.hostname or "").lower()
        if database_host in {"localhost", "127.0.0.1", "postgres", "db"}:
            errors.append("Release database must be isolated from the application host")
        if "sslmode=" not in database_url and "ssl=" not in database_url:
            warnings.append("DATABASE_URL does not visibly declare TLS; confirm provider-enforced TLS")

    if len(os.getenv("JWT_SECRET", "")) < 32:
        errors.append("JWT_SECRET must contain at least 32 characters")
    if os.getenv("BILLING_PROVIDER", "manual") != "manual":
        if len(os.getenv("BILLING_WEBHOOK_SECRET", "")) < 24:
            errors.append("Non-manual billing requires a webhook secret of at least 24 characters")
    else:
        warnings.append("Billing remains manual; online checkout is not production-ready")

    frontend_url = os.getenv("FRONTEND_URL", "")
    if target == "production" and not frontend_url.startswith("https://"):
        errors.append("Production FRONTEND_URL must use HTTPS")
    if target == "production" and any(
        token in os.getenv("CORS_ORIGINS", "").lower()
        for token in ("localhost", "127.0.0.1")
    ):
        errors.append("Production CORS origins must not include localhost")

    if os.getenv("MALWARE_SCAN_MODE") != "clamav":
        errors.append("Release uploads require MALWARE_SCAN_MODE=clamav")
    if not present("CLAMAV_HOST"):
        errors.append("CLAMAV_HOST is required")

    if truthy("AI_GLOBAL_ENABLED") and not truthy("AI_COMMERCIAL_PROVIDER_READY"):
        errors.append(
            "AI is enabled but AI_COMMERCIAL_PROVIDER_READY is not true; the shared CLI pilot is not a commercial release dependency"
        )
    if not truthy("AI_GLOBAL_ENABLED"):
        warnings.append("AI is disabled; deterministic editing, review and export may still be released")

    if target == "production":
        evidence_path = os.getenv("BACKUP_EVIDENCE_PATH", "").strip()
        if not evidence_path:
            errors.append("BACKUP_EVIDENCE_PATH is required for production")
        elif not Path(evidence_path).is_file():
            errors.append("BACKUP_EVIDENCE_PATH does not point to a readable file")

    result = {
        "ok": not errors,
        "target": target,
        "errors": errors,
        "warnings": warnings,
        "release_sha": os.getenv("RELEASE_SHA"),
        "storage_backend": os.getenv("STORAGE_BACKEND"),
        "database_host": database_host,
        "malware_scan_mode": os.getenv("MALWARE_SCAN_MODE"),
        "ai_enabled": truthy("AI_GLOBAL_ENABLED"),
        "billing_provider": os.getenv("BILLING_PROVIDER", "manual"),
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
