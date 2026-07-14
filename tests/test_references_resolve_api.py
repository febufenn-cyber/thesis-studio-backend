"""Reference-resolution API endpoints (docs/LLD.md 3.2)."""

from __future__ import annotations

import httpx
import pytest
from httpx import AsyncClient

import app.references.service as svc
from app.models.project import Project
from app.models.source import Source
from tests.conftest import auth_cookie

pytestmark = pytest.mark.asyncio

_CROSSREF = {
    "message": {
        "type": "journal-article",
        "title": ["Modern Fiction"],
        "author": [{"given": "Virginia", "family": "Woolf"}],
        "container-title": ["The Common Reader"],
        "publisher": "Hogarth",
        "volume": "1",
        "issue": "3",
        "page": "150-158",
        "DOI": "10.1000/xyz123",
        "issued": {"date-parts": [[1925]]},
    }
}


def _handler(request):
    if request.url.host == "api.crossref.org":
        return httpx.Response(200, json=_CROSSREF)
    return httpx.Response(404)


class _Settings:
    RESOLVER_ENABLED = True
    RESOLUTION_TTL_DAYS = 30


@pytest.fixture(autouse=True)
def _enable_resolver(monkeypatch):
    monkeypatch.setattr(svc, "get_settings", lambda: _Settings())
    monkeypatch.setattr(
        svc, "build_client",
        lambda transport=None: httpx.AsyncClient(transport=httpx.MockTransport(_handler)),
    )


async def _project(db_session, user) -> Project:
    project = Project(user_id=user.id, title="Resolve API", meta={}, front_matter=[], chapters=[], works_cited=[])
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


async def test_resolve_endpoint_returns_fields(client: AsyncClient, db_session, user_a) -> None:
    project = await _project(db_session, user_a)
    response = await client.post(
        f"/projects/{project.id}/references/resolve",
        json={"query": "10.1000/xyz123"},
        cookies=auth_cookie(user_a),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "resolved"
    assert body["identifier"] == {"kind": "doi", "value": "10.1000/xyz123"}
    assert body["fields"]["title"]["value"] == "Modern Fiction"
    assert body["fields"]["title"]["authority"] == "crossref"


async def test_resolve_is_owner_guarded(client: AsyncClient, db_session, user_a, user_b) -> None:
    project = await _project(db_session, user_a)
    response = await client.post(
        f"/projects/{project.id}/references/resolve",
        json={"query": "10.1000/xyz123"},
        cookies=auth_cookie(user_b),
    )
    assert response.status_code == 404


async def test_source_resolve_applies_fields(client: AsyncClient, db_session, user_a) -> None:
    project = await _project(db_session, user_a)
    source = Source(
        project_id=project.id,
        user_id=user_a.id,
        kind="journal",
        fields={k: "[VERIFY]" for k in
                ("author", "title", "container", "volume", "number", "year", "pages")},
        identifiers={"doi": "10.1000/xyz123"},
        parse_status="imported",
    )
    db_session.add(source)
    await db_session.commit()
    await db_session.refresh(source)

    response = await client.post(
        f"/projects/{project.id}/sources/{source.id}/resolve",
        json={"min_confidence": 0.75},
        cookies=auth_cookie(user_a),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["resolution_status"] == "resolved"
    assert "title" in body["applied_fields"]
    assert body["still_missing"] == []


async def test_source_resolve_unknown_source_404(client: AsyncClient, db_session, user_a) -> None:
    from uuid import uuid4
    project = await _project(db_session, user_a)
    response = await client.post(
        f"/projects/{project.id}/sources/{uuid4()}/resolve",
        json={},
        cookies=auth_cookie(user_a),
    )
    assert response.status_code == 404
