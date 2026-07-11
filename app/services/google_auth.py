"""Google Sign-In — ID-token verification via Google's JWKS.

Uses PyJWT + cryptography (both already installed); no google-auth dependency.
The JWKS fetch and RS256 verification are synchronous, so the async wrapper
runs them in a worker thread.
"""

from __future__ import annotations

import asyncio
import logging

import jwt

from app.core.config import get_settings


log = logging.getLogger(__name__)

_GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
_GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")

# PyJWKClient caches keys internally; module singleton avoids re-fetching.
_jwks_client: jwt.PyJWKClient | None = None


class GoogleAuthError(Exception):
    """The Google credential could not be verified."""


def _verify_sync(credential: str, client_id: str) -> dict:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = jwt.PyJWKClient(_GOOGLE_JWKS_URL, cache_keys=True)
    try:
        signing_key = _jwks_client.get_signing_key_from_jwt(credential)
        payload: dict = jwt.decode(
            credential,
            signing_key.key,
            algorithms=["RS256"],
            audience=client_id,
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise GoogleAuthError(f"token verification failed: {type(exc).__name__}") from exc
    if payload.get("iss") not in _GOOGLE_ISSUERS:
        raise GoogleAuthError("unexpected issuer")
    if not payload.get("email") or not payload.get("email_verified"):
        raise GoogleAuthError("email missing or unverified")
    return payload


async def verify_google_credential(credential: str) -> dict:
    """Verify a Google ID token; returns its payload (email, name, sub, …).

    Raises GoogleAuthError on any verification failure or when
    GOOGLE_CLIENT_ID is not configured.
    """
    client_id = get_settings().GOOGLE_CLIENT_ID
    if not client_id:
        raise GoogleAuthError("Google Sign-In is not configured")
    return await asyncio.to_thread(_verify_sync, credential, client_id)
