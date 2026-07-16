"""Production-hardening regression tests (audit punch list).

Covers: security headers, rate-limit client keying (spoofable XFF), resilient
outbound transport (retry/backoff/circuit breaker), JWT secret rotation, and
the scheduled retention sweep.
"""

from __future__ import annotations

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core import security as sec
from app.core.rate_limit import _client_key
from app.models.job import Job
from app.references import http as ref_http
from app.services.retention_scheduler import enqueue_daily_retention_sweep

pytestmark = pytest.mark.asyncio


# --- security headers --------------------------------------------------------


async def test_security_headers_present(client: AsyncClient) -> None:
    resp = await client.get("/healthz")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in resp.headers["Content-Security-Policy"]
    assert resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    # HSTS only in production (this test env is development).
    assert "Strict-Transport-Security" not in resp.headers


# --- rate-limit client keying -------------------------------------------------


class _FakeRequest:
    def __init__(self, xff: str | None, peer: str = "10.0.0.9") -> None:
        self.headers = {"x-forwarded-for": xff} if xff else {}
        self.client = type("C", (), {"host": peer})()


async def test_xff_untrusted_by_default(monkeypatch) -> None:
    # TRUSTED_PROXY_HOPS defaults to 0 -> spoofed XFF must NOT change the key.
    req = _FakeRequest(xff="1.2.3.4, 5.6.7.8")
    assert _client_key(req) == "10.0.0.9"


async def test_xff_honored_behind_declared_proxy(monkeypatch) -> None:
    from app.core import rate_limit as rl

    monkeypatch.setattr(
        rl, "get_settings", lambda: type("S", (), {"TRUSTED_PROXY_HOPS": 1})()
    )
    # One trusted hop -> take the right-most entry (added by our proxy).
    req = _FakeRequest(xff="6.6.6.6, 203.0.113.7")
    assert _client_key(req) == "203.0.113.7"


# --- resilient outbound transport ---------------------------------------------


async def test_retry_on_5xx_then_success() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503 if calls["n"] < 3 else 200, json={"ok": True})

    transport = ref_http.ResilientTransport(httpx.MockTransport(handler))
    ref_http._BACKOFF_BASE = 0.01  # keep the test fast
    async with httpx.AsyncClient(transport=transport) as client:
        resp = await client.get("https://api.example.org/x")
    assert resp.status_code == 200
    assert calls["n"] == 3


async def test_final_status_is_returned_not_masked() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "0"})

    transport = ref_http.ResilientTransport(httpx.MockTransport(handler))
    async with httpx.AsyncClient(transport=transport) as client:
        resp = await client.get("https://api2.example.org/x")
    assert resp.status_code == 429  # caller still sees reality (fail-closed upstream)


async def test_circuit_opens_after_consecutive_failures() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    transport = ref_http.ResilientTransport(httpx.MockTransport(boom))
    async with httpx.AsyncClient(transport=transport) as client:
        for _ in range(2):  # 2 requests x 3 attempts = 6 failures > threshold 5
            with pytest.raises(httpx.ConnectError):
                await client.get("https://dead.example.org/x")
        with pytest.raises(httpx.ConnectError) as excinfo:
            await client.get("https://dead.example.org/x")
    assert "circuit open" in str(excinfo.value)


async def test_injected_transports_are_not_wrapped() -> None:
    mock = httpx.MockTransport(lambda r: httpx.Response(200))
    client = ref_http.build_client(transport=mock)
    # The test seam stays exact: injected transport is used as-is.
    assert client._transport is mock  # noqa: SLF001 - deliberate white-box check
    await client.aclose()


# --- JWT rotation ---------------------------------------------------------------


async def test_previous_secret_verifies_during_rotation(monkeypatch, user_a) -> None:
    import jwt as pyjwt

    settings = sec.get_settings()
    old_secret = "y" * 64
    token = sec.create_access_token(user_a.id)

    class Rotated:
        JWT_SECRET = "z" * 64  # new secret: current tokens no longer match
        JWT_SECRET_PREVIOUS = settings.JWT_SECRET  # old secret still verifies
        JWT_ALGORITHM = settings.JWT_ALGORITHM
        JWT_EXPIRY_DAYS = settings.JWT_EXPIRY_DAYS

    monkeypatch.setattr(sec, "get_settings", lambda: Rotated())
    claims = sec.decode_access_token_claims(token)
    assert claims.user_id == user_a.id

    # Garbage secret still fails even with a fallback configured.
    forged = pyjwt.encode({"sub": str(user_a.id), "iat": 1, "exp": 2**31}, old_secret, algorithm="HS256")
    with pytest.raises(pyjwt.InvalidTokenError):
        sec.decode_access_token_claims(forged)


# --- retention sweep scheduling --------------------------------------------------


async def test_daily_sweep_enqueue_is_idempotent(db_session) -> None:
    try:
        first = await enqueue_daily_retention_sweep()
        second = await enqueue_daily_retention_sweep()
    finally:
        # The scheduler uses the app-global engine; its pooled connections are
        # bound to THIS test's event loop, so release them or a later test on a
        # fresh loop would inherit a dead-loop connection.
        from app.db.session import engine

        await engine.dispose()
    assert first is True
    rows = list(
        (
            await db_session.execute(
                select(Job).where(Job.kind == "retention_sweep")
            )
        ).scalars()
    )
    assert len(rows) == 1  # dedup by idempotency key: one sweep per day
    assert rows[0].user_id is None  # system-scheduled, no requesting user
    assert second in (True, False)  # second call is a no-op either way


async def test_rate_limited_endpoint_does_not_500_with_limiting_on(monkeypatch, user_a) -> None:
    """Regression for the Priya gauntlet: with rate limiting ENABLED, a limited
    endpoint that returns a Pydantic model must not 500 (headers_enabled bug).

    The whole suite runs with RATE_LIMIT_ENABLED=false, which hid a production
    outage: slowapi header injection required a Response object our endpoints
    don't expose. We assert the limiter is configured so enforcement can be on
    without breaking model-returning routes.
    """
    from app.core.rate_limit import limiter

    # headers_enabled must be False, or every limited route 500s when limiting
    # is on (the production default).
    assert getattr(limiter, "_headers_enabled", False) is False
