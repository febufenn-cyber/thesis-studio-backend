"""Research copilot — Semantic Scholar insight (enterprise E3)."""

from __future__ import annotations

import httpx
import pytest
from httpx import AsyncClient

import app.api.copilot as cp
from app.models.project import Project
from app.models.source import Source
from app.references.copilot import paper_insight
from tests.conftest import auth_cookie

pytestmark = pytest.mark.asyncio

_S2 = {
    "title": "Attention Is All You Need",
    "tldr": {"text": "A transformer using only attention outperforms recurrence."},
    "citationCount": 120000, "referenceCount": 40,
    "references": [{"title": "Neural MT by Jointly Learning", "externalIds": {"DOI": "10.48550/1409.0473"}}],
    "citations": [{"title": "BERT", "externalIds": {"DOI": "10.18653/bert"}}, {"title": "GPT-3"}],
}


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_insight_parses_tldr_and_related() -> None:
    async with _client(lambda r: httpx.Response(200, json=_S2)) as client:
        ins = await paper_insight(client, "10.5555/attn")
    assert ins["found"] is True
    assert "transformer" in ins["tldr"]
    assert ins["citation_count"] == 120000
    assert ins["references"][0]["doi"] == "10.48550/1409.0473"
    assert {c["title"] for c in ins["citations"]} == {"BERT", "GPT-3"}


async def test_no_doi_returns_empty() -> None:
    async with _client(lambda r: httpx.Response(200, json=_S2)) as client:
        ins = await paper_insight(client, "")
    assert ins["found"] is False and ins["tldr"] is None


async def test_error_fails_closed() -> None:
    def boom(request):
        raise httpx.ConnectError("down", request=request)
    async with _client(boom) as client:
        ins = await paper_insight(client, "10.5555/attn")
    assert ins["found"] is False


async def test_insight_endpoint(client: AsyncClient, db_session, user_a, monkeypatch) -> None:
    project = Project(user_id=user_a.id, title="T", meta={}, front_matter=[], chapters=[], works_cited=[])
    db_session.add(project)
    await db_session.flush()
    source = Source(project_id=project.id, user_id=user_a.id, kind="journal",
                    fields={"doi_or_url": "10.5555/attn"}, parse_status="imported")
    db_session.add(source)
    await db_session.commit()
    await db_session.refresh(project)
    await db_session.refresh(source)

    monkeypatch.setattr(cp, "get_settings", lambda: type("S", (), {"COPILOT_ENABLED": True, "SEMANTIC_SCHOLAR_API_KEY": ""})())
    monkeypatch.setattr(cp, "build_client", lambda transport=None: _client(lambda r: httpx.Response(200, json=_S2)))
    resp = await client.get(f"/projects/{project.id}/sources/{source.id}/insight", cookies=auth_cookie(user_a))
    assert resp.status_code == 200
    body = resp.json()
    assert body["advisory"] is True
    assert "transformer" in body["tldr"]
