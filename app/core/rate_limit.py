"""Application-layer rate limiting (slowapi).

Defense-in-depth on the unauthenticated and auth-adjacent surfaces (magic-link /
OTP issue, the billing webhook, external-review downloads). Edge WAF / Cloudflare
remains the first line; this guards the app directly so brute-force and flood
resistance does not depend entirely on infrastructure being configured.

Counters are per-process and in-memory: with multiple web replicas each enforces
its own share, which is acceptable for a defensive backstop. The limiter respects
Settings.RATE_LIMIT_ENABLED, so tests (and any environment that fronts its own
limiter) can disable it.
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import get_settings


def _client_key(request) -> str:
    """Prefer the real client IP behind the trusted proxy, else the peer."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return get_remote_address(request)


limiter = Limiter(
    key_func=_client_key,
    enabled=get_settings().RATE_LIMIT_ENABLED,
    headers_enabled=True,
)


__all__ = ["limiter"]
