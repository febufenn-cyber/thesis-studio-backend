"""AI provenance API — summary, timeline, AI Use Statement (docs/LLD.md 3.1)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.models.project import Project
from tests.conftest import auth_cookie

pytestmark = pytest.mark.asyncio


async def _project(db_session, user) -> Project:
    project = Project(
        user_id=user.id,
        title="Prov API",
        meta={"title": "Prov API Thesis"},
        front_matter=[],
        chapters=[
            {
                "number": 1,
                "title": "Intro",
                "blocks": [
                    {"type": "paragraph", "runs": [{"text": "a"}], "origin": "human"},
                    {"type": "paragraph", "runs": [{"text": "b"}], "origin": "ai_proposal"},
                ],
            }
        ],
        works_cited=[],
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


async def test_summary_returns_origin_counts(client: AsyncClient, db_session, user_a) -> None:
    project = await _project(db_session, user_a)
    response = await client.get(
        f"/projects/{project.id}/provenance/summary", cookies=auth_cookie(user_a)
    )
    assert response.status_code == 200
    body = response.json()
    assert body["rollup"]["origin_counts"]["human"] == 1
    assert body["rollup"]["origin_counts"]["ai_proposal"] == 1
    assert any(t["key"] == "neurips" for t in body["templates"])


async def test_summary_is_owner_guarded(client: AsyncClient, db_session, user_a, user_b) -> None:
    project = await _project(db_session, user_a)
    response = await client.get(
        f"/projects/{project.id}/provenance/summary", cookies=auth_cookie(user_b)
    )
    assert response.status_code == 404


async def test_generate_and_read_statement(client: AsyncClient, db_session, user_a) -> None:
    project = await _project(db_session, user_a)

    # No statement yet.
    missing = await client.get(
        f"/projects/{project.id}/ai-use-statement", cookies=auth_cookie(user_a)
    )
    assert missing.status_code == 404

    created = await client.post(
        f"/projects/{project.id}/ai-use-statement",
        json={"template_key": "generic_university"},
        cookies=auth_cookie(user_a),
    )
    assert created.status_code == 201
    body = created.json()
    assert body["template_key"] == "generic_university"
    assert body["body_text"]
    assert len(body["content_hash"]) == 64
    assert body["document_version"] == project.document_version

    fetched = await client.get(
        f"/projects/{project.id}/ai-use-statement", cookies=auth_cookie(user_a)
    )
    assert fetched.status_code == 200
    assert fetched.json()["id"] == body["id"]


async def test_unknown_template_is_409(client: AsyncClient, db_session, user_a) -> None:
    project = await _project(db_session, user_a)
    response = await client.post(
        f"/projects/{project.id}/ai-use-statement",
        json={"template_key": "does-not-exist"},
        cookies=auth_cookie(user_a),
    )
    assert response.status_code == 409


async def test_timeline_is_empty_without_proposals(client: AsyncClient, db_session, user_a) -> None:
    project = await _project(db_session, user_a)
    response = await client.get(
        f"/projects/{project.id}/provenance/timeline", cookies=auth_cookie(user_a)
    )
    assert response.status_code == 200
    assert response.json()["events"] == []
