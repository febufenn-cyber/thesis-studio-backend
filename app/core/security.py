"""Security utilities — JWT encoding/decoding and magic-link token handling."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt

from app.core.config import get_settings


# ---------------------------------------------------------------------------
# JWT (session tokens)
# ---------------------------------------------------------------------------

def create_access_token(user_id: UUID) -> str:
    """Create a JWT access token for the given user."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=settings.JWT_EXPIRY_DAYS)).timestamp()),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> UUID:
    """Decode a JWT and return the user_id. Raises jwt.PyJWTError on failure."""
    settings = get_settings()
    payload = jwt.decode(
        token,
        settings.JWT_SECRET,
        algorithms=[settings.JWT_ALGORITHM],
    )
    return UUID(payload["sub"])


# ---------------------------------------------------------------------------
# Magic-link tokens
# ---------------------------------------------------------------------------

def generate_magic_link_token() -> tuple[str, str]:
    """
    Generate a fresh magic-link token.

    Returns:
        (raw_token, hashed_token):
            - raw_token: send to user via email
            - hashed_token: store in DB. The raw token is never persisted.
    """
    raw_token = secrets.token_urlsafe(32)
    hashed_token = hash_magic_link_token(raw_token)
    return raw_token, hashed_token


def hash_magic_link_token(raw_token: str) -> str:
    """SHA-256 hash of a magic-link token. Used for both generation and verification."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Email domain validation
# ---------------------------------------------------------------------------

def is_email_domain_allowed(email: str) -> bool:
    """Check if the email's domain is in the institutional allowlist."""
    settings = get_settings()
    if "@" not in email:
        return False
    domain = email.split("@", 1)[1].strip().lower()
    return domain in settings.allowed_email_domains_list
