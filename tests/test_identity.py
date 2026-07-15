"""Verified identity — ROR + ORCID (enterprise E2)."""

from __future__ import annotations

import httpx
import pytest
from httpx import AsyncClient

import app.api.identity as ident
from app.integrations.orcid import OrcidClient
from app.integrations.ror import search_organizations
from tests.conftest import auth_cookie

pytestmark = pytest.mark.asyncio

_ROR = {"items": [
    {"id": "https://ror.org/02mhbdp94", "name": "Madras Christian College",
     "country": {"country_name": "India"}, "established": 1837},
    {"id": "https://ror.org/00000zz00", "name": "Other College", "country": {"country_name": "India"}},
]}
_ORCID = {"name": {"given-names": {"value": "Jane"}, "family-name": {"value": "Doe"}}}


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_ror_search_returns_canonical_matches() -> None:
    async with _client(lambda r: httpx.Response(200, json=_ROR)) as client:
        matches = await search_organizations(client, "Madras Christian College")
    assert matches[0]["ror_id"] == "https://ror.org/02mhbdp94"
    assert matches[0]["name"] == "Madras Christian College"
    assert matches[0]["country"] == "India"


async def test_ror_error_fails_closed() -> None:
    def boom(request):
        raise httpx.ConnectError("down", request=request)
    async with _client(boom) as client:
        assert await search_organizations(client, "x") == []


async def test_orcid_resolve_returns_name() -> None:
    async with _client(lambda r: httpx.Response(200, json=_ORCID)) as client:
        rec = await OrcidClient(client).resolve("0000-0002-1825-0097")
    assert rec == {"orcid": "0000-0002-1825-0097", "name": "Jane Doe"}


async def test_orcid_resolve_malformed_is_none() -> None:
    async with _client(lambda r: httpx.Response(200, json={})) as client:
        assert await OrcidClient(client).resolve("not-orcid") is None


async def test_org_endpoint(client: AsyncClient, user_a, monkeypatch) -> None:
    monkeypatch.setattr(ident, "get_settings", lambda: type("S", (), {"IDENTITY_LOOKUP_ENABLED": True})())
    monkeypatch.setattr(ident, "build_client", lambda transport=None: _client(lambda r: httpx.Response(200, json=_ROR)))
    resp = await client.get("/identity/organizations?q=Madras", cookies=auth_cookie(user_a))
    assert resp.status_code == 200
    assert resp.json()["matches"][0]["name"] == "Madras Christian College"


async def test_orcid_endpoint(client: AsyncClient, user_a, monkeypatch) -> None:
    monkeypatch.setattr(ident, "get_settings", lambda: type("S", (), {"IDENTITY_LOOKUP_ENABLED": True})())
    monkeypatch.setattr(ident, "build_client", lambda transport=None: _client(lambda r: httpx.Response(200, json=_ORCID)))
    ok = await client.get("/identity/orcid/0000-0002-1825-0097", cookies=auth_cookie(user_a))
    assert ok.status_code == 200
    assert ok.json() == {"orcid": "0000-0002-1825-0097", "name": "Jane Doe", "verified": True}
    bad = await client.get("/identity/orcid/not-an-orcid", cookies=auth_cookie(user_a))
    assert bad.status_code == 422
