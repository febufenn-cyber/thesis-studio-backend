"""Zotero library import (MF5)."""

from __future__ import annotations

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select

import app.api.references_import as ri
from app.models.project import Project
from app.models.source import Source
from tests.conftest import auth_cookie

pytestmark = pytest.mark.asyncio

_CSLJSON = {"items": [
    {"type": "book", "title": "Emma", "author": [{"family": "Austen", "given": "Jane"}],
     "issued": {"date-parts": [[1815]]}, "publisher": "John Murray"},
    {"type": "article-journal", "title": "Modern Fiction",
     "author": [{"family": "Woolf", "given": "Virginia"}],
     "container-title": "The Common Reader", "issued": {"date-parts": [[1925]]},
     "volume": "1", "issue": "3", "page": "150-158", "DOI": "10.1000/mf"},
]}

_CROSSREF_WORK = {"message": {
    "type": "book", "title": ["Emma"], "author": [{"family": "Austen", "given": "Jane"}],
    "publisher": "John Murray", "DOI": "10.1000/emma", "issued": {"date-parts": [[1815]]},
}}


def _handler(request):
    host = request.url.host
    if host == "api.zotero.org":
        return httpx.Response(200, json=_CSLJSON, headers={"Last-Modified-Version": "42"})
    if host == "api.crossref.org":
        return httpx.Response(200, json=_CROSSREF_WORK)
    return httpx.Response(404)


def _bad_key_handler(request):
    return httpx.Response(403)


async def _project(db_session, user) -> Project:
    project = Project(user_id=user.id, title="Z", meta={}, front_matter=[], chapters=[], works_cited=[])
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


async def test_zotero_import_creates_sources(client: AsyncClient, db_session, user_a, monkeypatch) -> None:
    project = await _project(db_session, user_a)
    monkeypatch.setattr(ri, "build_client", lambda transport=None: httpx.AsyncClient(transport=httpx.MockTransport(_handler)))

    response = await client.post(
        f"/projects/{project.id}/references/zotero/import",
        json={"api_key": "k", "library_id": "123"},
        cookies=auth_cookie(user_a),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["imported"] == 2
    assert body["library_version"] == 42

    sources = list((await db_session.execute(select(Source).where(Source.project_id == project.id))).scalars())
    assert len(sources) == 2
    assert all(s.verified is False and s.parse_status == "imported" for s in sources)
    titles = {s.fields.get("title") for s in sources}
    assert "Emma" in titles


async def test_zotero_bad_key_is_400_no_writes(client: AsyncClient, db_session, user_a, monkeypatch) -> None:
    project = await _project(db_session, user_a)
    monkeypatch.setattr(ri, "build_client", lambda transport=None: httpx.AsyncClient(transport=httpx.MockTransport(_bad_key_handler)))
    response = await client.post(
        f"/projects/{project.id}/references/zotero/import",
        json={"api_key": "bad", "library_id": "123"},
        cookies=auth_cookie(user_a),
    )
    assert response.status_code == 400
    sources = list((await db_session.execute(select(Source).where(Source.project_id == project.id))).scalars())
    assert sources == []


async def test_zotero_import_owner_guarded(client: AsyncClient, db_session, user_a, user_b, monkeypatch) -> None:
    project = await _project(db_session, user_a)
    monkeypatch.setattr(ri, "build_client", lambda transport=None: httpx.AsyncClient(transport=httpx.MockTransport(_handler)))
    response = await client.post(
        f"/projects/{project.id}/references/zotero/import",
        json={"api_key": "k", "library_id": "123"},
        cookies=auth_cookie(user_b),
    )
    assert response.status_code == 404
