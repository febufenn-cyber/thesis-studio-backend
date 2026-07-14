"""HTTP client factory for reference resolvers.

Centralizes the polite User-Agent / mailto convention the bibliographic APIs
ask for, and gives tests a single seam to inject an ``httpx.MockTransport`` so
resolution runs fully offline and deterministically.
"""

from __future__ import annotations

import httpx

from app.core.config import get_settings

_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


def build_client(transport: httpx.AsyncTransport | None = None) -> httpx.AsyncClient:
    """Return a shared async client with a polite UA. Pass ``transport`` in tests."""
    settings = get_settings()
    mailto = getattr(settings, "CROSSREF_MAILTO", "") or settings.EMAIL_FROM_ADDRESS
    headers = {
        "User-Agent": f"Acadensia/0.7 (reference-resolver; mailto:{mailto})",
        "Accept": "application/json",
    }
    return httpx.AsyncClient(
        headers=headers,
        timeout=_TIMEOUT,
        transport=transport,
        follow_redirects=True,
    )
