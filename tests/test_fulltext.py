"""Open-access full text + auto quote-verify (enterprise E4).

Europe PMC full text feeds Phase 3 quote verification with no upload. Fail-closed:
no OA text -> the quote is 'unverifiable', never 'verified'. Fully offline via
httpx.MockTransport.
"""

from __future__ import annotations

import httpx
import pytest
from httpx import AsyncClient

import app.api.quote_verification as qv
from app.models.project import Project
from app.models.quote import Quote
from app.models.source import Source
from app.references.fulltext import fetch_fulltext, oa_link
from tests.conftest import auth_cookie

pytestmark = pytest.mark.asyncio

_QUOTE = "attention is all you need for sequence transduction"
_FULLTEXT_XML = (
    "<article><body><p>In this work we show that "
    "attention is all you need for sequence transduction, "
    "dispensing with recurrence entirely.</p></body></html>"
)


def _epmc_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.endswith("/search"):
        return httpx.Response(
            200,
            json={"resultList": {"result": [{"isOpenAccess": "Y", "source": "MED", "id": "9001"}]}},
        )
    if path.endswith("/fullTextXML"):
        return httpx.Response(200, text=_FULLTEXT_XML)
    return httpx.Response(404)


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_fetch_fulltext_open_access() -> None:
    async with _client(_epmc_handler) as client:
        found = await fetch_fulltext(client, "10.5555/attn")
    assert found is not None
    assert found["provider"] == "europepmc"
    assert "attention is all you need" in found["text"]


async def test_fetch_fulltext_closed_access_returns_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/search"):
            return httpx.Response(
                200,
                json={"resultList": {"result": [{"isOpenAccess": "N", "source": "MED", "id": "9001"}]}},
            )
        return httpx.Response(200, text=_FULLTEXT_XML)

    async with _client(handler) as client:
        found = await fetch_fulltext(client, "10.5555/closed")
    assert found is None


async def test_fetch_fulltext_bad_doi_returns_none() -> None:
    async with _client(_epmc_handler) as client:
        assert await fetch_fulltext(client, "") is None
        assert await fetch_fulltext(client, "not-a-doi") is None


async def test_fetch_fulltext_error_fails_closed() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    async with _client(boom) as client:
        assert await fetch_fulltext(client, "10.5555/attn") is None


async def test_oa_link_needs_email(monkeypatch) -> None:
    # No configured email -> no network, None.
    monkeypatch.setattr(
        "app.references.fulltext.get_settings",
        lambda: type("S", (), {"UNPAYWALL_EMAIL": ""})(),
    )
    async with _client(lambda r: httpx.Response(200, json={})) as client:
        assert await oa_link(client, "10.5555/attn") is None


async def test_oa_link_returns_best_location(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.references.fulltext.get_settings",
        lambda: type("S", (), {"UNPAYWALL_EMAIL": "dev@example.com"})(),
    )
    payload = {"is_oa": True, "best_oa_location": {"url_for_pdf": "https://oa.example/paper.pdf"}}
    async with _client(lambda r: httpx.Response(200, json=payload)) as client:
        link = await oa_link(client, "10.5555/attn")
    assert link == {"url": "https://oa.example/paper.pdf", "is_oa": True, "provider": "unpaywall"}


async def _project_source_quote(db_session, user, *, doi: str, quote_text: str):
    project = Project(user_id=user.id, title="E4", meta={}, front_matter=[], chapters=[], works_cited=[])
    db_session.add(project)
    await db_session.flush()
    fields = {"doi_or_url": doi} if doi else {}
    source = Source(project_id=project.id, user_id=user.id, kind="journal", fields=fields, parse_status="imported")
    db_session.add(source)
    await db_session.flush()
    quote = Quote(source_id=source.id, project_id=project.id, user_id=user.id, text=quote_text, page_or_loc="1")
    db_session.add(quote)
    await db_session.commit()
    await db_session.refresh(project)
    await db_session.refresh(quote)
    return project, quote


async def test_verify_auto_uses_open_access_fulltext(client: AsyncClient, db_session, user_a, monkeypatch) -> None:
    project, quote = await _project_source_quote(db_session, user_a, doi="10.5555/attn", quote_text=_QUOTE)
    monkeypatch.setattr(qv, "get_settings", lambda: type("S", (), {"FULLTEXT_ENABLED": True})())
    monkeypatch.setattr(qv, "build_client", lambda transport=None: _client(_epmc_handler))

    resp = await client.post(
        f"/projects/{project.id}/quotes/{quote.id}/verify-auto", cookies=auth_cookie(user_a)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "verified"
    assert body["advisory"] is True
    assert body["fulltext_provider"] == "europepmc"
    # Human-verify bit is never touched.
    await db_session.refresh(quote)
    assert quote.verified is False


async def test_verify_auto_no_doi_is_unverifiable(client: AsyncClient, db_session, user_a, monkeypatch) -> None:
    project, quote = await _project_source_quote(db_session, user_a, doi="", quote_text=_QUOTE)
    monkeypatch.setattr(qv, "get_settings", lambda: type("S", (), {"FULLTEXT_ENABLED": True})())
    monkeypatch.setattr(qv, "build_client", lambda transport=None: _client(_epmc_handler))

    resp = await client.post(
        f"/projects/{project.id}/quotes/{quote.id}/verify-auto", cookies=auth_cookie(user_a)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "unverifiable"
    assert body["fulltext_provider"] is None


async def test_verify_auto_owner_guarded(client: AsyncClient, db_session, user_a, user_b, monkeypatch) -> None:
    project, quote = await _project_source_quote(db_session, user_a, doi="10.5555/attn", quote_text=_QUOTE)
    monkeypatch.setattr(qv, "get_settings", lambda: type("S", (), {"FULLTEXT_ENABLED": True})())
    monkeypatch.setattr(qv, "build_client", lambda transport=None: _client(_epmc_handler))
    resp = await client.post(
        f"/projects/{project.id}/quotes/{quote.id}/verify-auto", cookies=auth_cookie(user_b)
    )
    assert resp.status_code == 404
