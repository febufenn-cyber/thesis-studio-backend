"""Security utilities — signed session tokens and one-time auth tokens."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt

from app.core.config import get_settings


@dataclass(frozen=True)
class AccessTokenClaims:
    user_id: UUID
    session_id: UUID | None
    issued_at: datetime
    expires_at: datetime


def create_access_token(user_id: UUID, *, session_id: UUID | None = None) -> str:
    """Create a short transport token bound to a revocable server session."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=settings.JWT_EXPIRY_DAYS)).timestamp()),
        "ver": 2,
    }
    if session_id is not None:
        payload["sid"] = str(session_id)
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_access_token_claims(token: str) -> AccessTokenClaims:
    settings = get_settings()
    # Rotation-aware verification: the current secret is tried first; during a
    # rotation window JWT_SECRET_PREVIOUS is accepted for verification only
    # (new tokens are always signed with the current secret). Clear the
    # previous secret once outstanding tokens have expired.
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except jwt.InvalidSignatureError:
        previous = getattr(settings, "JWT_SECRET_PREVIOUS", "")
        if not previous:
            raise
        payload = jwt.decode(
            token,
            previous,
            algorithms=[settings.JWT_ALGORITHM],
        )
    issued = datetime.fromtimestamp(int(payload["iat"]), tz=timezone.utc)
    expires = datetime.fromtimestamp(int(payload["exp"]), tz=timezone.utc)
    return AccessTokenClaims(
        user_id=UUID(payload["sub"]),
        session_id=UUID(payload["sid"]) if payload.get("sid") else None,
        issued_at=issued,
        expires_at=expires,
    )


def decode_access_token(token: str) -> UUID:
    """Backwards-compatible helper returning only the subject user ID."""
    return decode_access_token_claims(token).user_id


def generate_magic_link_token() -> tuple[str, str]:
    raw_token = secrets.token_urlsafe(32)
    return raw_token, hash_magic_link_token(raw_token)


def hash_magic_link_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
