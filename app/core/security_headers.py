"""Security response headers (defense-in-depth).

Every response gets clickjacking, MIME-sniffing, referrer and permissions
protection; HSTS is added only in production (it is meaningless — and sticky —
over plain HTTP in development). The CSP is pragmatic rather than maximal: the
served legacy app and the SPA bootstrap rely on inline scripts/styles, so
'unsafe-inline' is allowed, but remote script origins are pinned to self — a
stored-XSS payload cannot pull an external payload, exfiltrate via forms, or
frame the app. Tighten script-src to nonces once the inline bootstraps move
into the bundles.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import get_settings

_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://accounts.google.com; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data:; "
    "connect-src 'self' https://accounts.google.com; "
    "frame-src https://accounts.google.com; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        settings = get_settings()
        if not getattr(settings, "SECURITY_HEADERS_ENABLED", True):
            return response
        headers = response.headers
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()"
        )
        headers.setdefault("Content-Security-Policy", _CSP)
        if settings.ENV == "production":
            headers.setdefault(
                "Strict-Transport-Security", "max-age=63072000; includeSubDomains"
            )
        return response
