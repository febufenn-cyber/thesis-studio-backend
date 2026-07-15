"""Literature discovery search + add-to-registry (MF1)."""

from __future__ import annotations

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select

import app.references.search.service as search_service
from app.models.project import Project
from app.models.source import Source
from app.references.search import search
from tests.conftest import auth_cookie

pytestmark = pytest.mark.asyncio

_OPENALEX = {"results": [
    {"title": "Attention Is All You Need", "doi": "https://doi.org/10.1000/attn",
     "authorships": [{"author": {"display_name": "A Vaswani"}}],
     "primary_location": {"source": {"display_name": "NeurIPS"}}, "publication_year": 2017},
]}
_CROSSREF_SEARCH = {"message": {"items": [
    {"title": ["Attention Is All You Need"], "DOI": "10.1000/attn",
     "author": [{"family": "Vaswani", "given": "A"}],
     "container-title": ["NeurIPS"], "issued": {"date-parts": [[2017]]}},
    {"title": ["A Different Paper"], "DOI": "10.1000/diff",
     "author": [{"family": "Smith", "given": "J"}], "issued": {"date-parts": [[2020]]}},
]}}
_CROSSREF_WORK = {"message": {
    "type": "journal-article", "title": ["Attention Is All You Need"],
    "author": [{"family": "Vaswani", "given": "Ashish"}],
    "container-title": ["NeurIPS"], "volume": "30", "issue": "1", "page": "1-11",
    "DOI": "10.1000/attn", "issued": {"date-parts": [[2017]]},
}}


def _handler(request):
    host = request.url.host
    query = request.url.query  # bytes
    if host == "api.openalex.org":
        # search uses ?search=...; resolve uses /works/doi:... (no 'search' param)
        return httpx.Response(200, json=_OPENALEX) if b"search" in query else httpx.Response(404)
    if host == "api.crossref.org":
        # search uses ?query=...; resolve uses /works/{doi}
        return httpx.Response(200, json=_CROSSREF_SEARCH) if b"query" in query else httpx.Response(200, json=_CROSSREF_WORK)
    return httpx.Response(404)


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(_handler))


async def _project(db_session, user) -> Project:
    project = Project(user_id=user.id, title="Search", meta={}, front_matter=[], chapters=[], works_cited=[])
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


async def test_search_dedups_by_doi(db_session, user_a) -> None:
    async with _client() as client:
        candidates = await search(db_session, "attention transformer", client=client)
    dois = [c.doi for c in candidates]
    # OpenAlex + Crossref both return 10.1000/attn -> collapsed to one.
    assert dois.count("10.1000/attn") == 1
    assert any(c.doi == "10.1000/diff" for c in candidates)


async def test_add_candidate_creates_verified_source(client: AsyncClient, db_session, user_a, monkeypatch) -> None:
    project = await _project(db_session, user_a)
    # add_candidate -> resolve_one(client=None) -> build_client(); patch the service
    # module's client + settings so resolution runs offline against the mock.
    import app.references.service as svc
    monkeypatch.setattr(svc, "get_settings", lambda: type("S", (), {"RESOLVER_ENABLED": True, "RESOLUTION_TTL_DAYS": 30})())
    monkeypatch.setattr(svc, "build_client", lambda transport=None: _client())

    response = await client.post(
        f"/projects/{project.id}/references/search/add",
        json={"identifier": "10.1000/attn"},
        cookies=auth_cookie(user_a),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["resolution_status"] == "resolved"
    assert "title" in body["applied_fields"]

    sources = list((await db_session.execute(select(Source).where(Source.project_id == project.id))).scalars())
    assert len(sources) == 1
    assert sources[0].fields["title"] == "Attention Is All You Need"
    assert sources[0].verified is False  # never auto-verified


async def test_search_owner_guarded(client: AsyncClient, db_session, user_a, user_b) -> None:
    project = await _project(db_session, user_a)
    response = await client.get(
        f"/projects/{project.id}/references/search?q=test", cookies=auth_cookie(user_b)
    )
    assert response.status_code == 404


async def test_search_disabled_returns_empty(db_session, user_a) -> None:
    # No client injected and LITERATURE_SEARCH_ENABLED=false in conftest -> empty.
    assert await search(db_session, "anything") == []
