"""HTTP client factory for reference resolvers.

Centralizes the polite User-Agent / mailto convention the bibliographic APIs
ask for, and gives tests a single seam to inject an ``httpx.MockTransport`` so
resolution runs fully offline and deterministically.

Real-network calls (no injected transport) go through ``ResilientTransport``:
bounded retries with exponential backoff on connect errors / 429 / 5xx
(honoring ``Retry-After``), plus a small per-host circuit breaker so a
provider outage or 429 storm stops being hammered — protecting both latency
and the app's shared outbound IP with the free scholarly APIs. Injected test
transports are used as-is, so offline tests keep exact call counts.
"""

from __future__ import annotations

import asyncio
import time

import httpx

from app.core.config import get_settings

_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

_RETRY_STATUSES = {429, 500, 502, 503, 504}
_MAX_RETRIES = 2  # total attempts = 1 + retries
_BACKOFF_BASE = 0.5  # seconds; doubled per retry
_BREAKER_THRESHOLD = 5  # consecutive failures per host to open
_BREAKER_COOLDOWN = 60.0  # seconds before a half-open probe


class _HostBreaker:
    """Per-host consecutive-failure circuit breaker (in-process)."""

    def __init__(self) -> None:
        self._failures: dict[str, int] = {}
        self._opened_at: dict[str, float] = {}

    def allow(self, host: str) -> bool:
        opened = self._opened_at.get(host)
        if opened is None:
            return True
        if time.monotonic() - opened >= _BREAKER_COOLDOWN:
            return True  # half-open: allow one probe through
        return False

    def record(self, host: str, ok: bool) -> None:
        if ok:
            self._failures.pop(host, None)
            self._opened_at.pop(host, None)
            return
        count = self._failures.get(host, 0) + 1
        self._failures[host] = count
        if count >= _BREAKER_THRESHOLD:
            self._opened_at[host] = time.monotonic()


_breaker = _HostBreaker()


class ResilientTransport(httpx.AsyncBaseTransport):
    """Retry/backoff + circuit breaker around a real transport."""

    def __init__(self, inner: httpx.AsyncBaseTransport) -> None:
        self._inner = inner

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host or ""
        if not _breaker.allow(host):
            raise httpx.ConnectError(
                f"circuit open for {host} (recent failures); retry later", request=request
            )
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                response = await self._inner.handle_async_request(request)
            except (httpx.ConnectError, httpx.ReadError, httpx.ConnectTimeout, httpx.ReadTimeout) as exc:
                last_exc = exc
                _breaker.record(host, ok=False)
            else:
                if response.status_code not in _RETRY_STATUSES:
                    _breaker.record(host, ok=True)
                    return response
                _breaker.record(host, ok=False)
                if attempt == _MAX_RETRIES:
                    return response  # give the caller the real status (fail-closed upstream)
                retry_after = response.headers.get("Retry-After")
                await response.aclose()
                delay = _BACKOFF_BASE * (2**attempt)
                if retry_after:
                    try:
                        delay = max(delay, min(float(retry_after), 15.0))
                    except ValueError:
                        pass
                await asyncio.sleep(delay)
                continue
            if attempt == _MAX_RETRIES:
                break
            await asyncio.sleep(_BACKOFF_BASE * (2**attempt))
        assert last_exc is not None
        raise last_exc

    async def aclose(self) -> None:
        await self._inner.aclose()


def build_client(transport: httpx.AsyncTransport | None = None) -> httpx.AsyncClient:
    """Return a shared async client with a polite UA. Pass ``transport`` in tests."""
    settings = get_settings()
    mailto = getattr(settings, "CROSSREF_MAILTO", "") or settings.EMAIL_FROM_ADDRESS
    headers = {
        "User-Agent": f"Acadensia/0.7 (reference-resolver; mailto:{mailto})",
        "Accept": "application/json",
    }
    if transport is None:
        # Real network: wrap the default pooled transport with resilience.
        transport = ResilientTransport(httpx.AsyncHTTPTransport())
    return httpx.AsyncClient(
        headers=headers,
        timeout=_TIMEOUT,
        transport=transport,
        follow_redirects=True,
    )
