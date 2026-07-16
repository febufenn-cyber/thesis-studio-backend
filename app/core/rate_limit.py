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
    """Rate-limit key: the real client IP — without trusting spoofable headers.

    X-Forwarded-For is attacker-controlled unless a proxy we operate appended
    to it, so it is honored only when TRUSTED_PROXY_HOPS > 0, and then the
    entry chosen is the one added by our outermost trusted proxy (counting
    from the right), not the client-supplied left-most value.
    """
    hops = int(getattr(get_settings(), "TRUSTED_PROXY_HOPS", 0))
    if hops > 0:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            chain = [part.strip() for part in forwarded.split(",") if part.strip()]
            if chain:
                return chain[-hops] if hops <= len(chain) else chain[0]
    return get_remote_address(request)


limiter = Limiter(
    key_func=_client_key,
    enabled=get_settings().RATE_LIMIT_ENABLED,
    headers_enabled=True,
)


__all__ = ["limiter"]
