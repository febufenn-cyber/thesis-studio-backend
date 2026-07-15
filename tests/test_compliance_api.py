"""Compliance endpoint (docs/LLD.md 3.4)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.models.project import Project
from tests.conftest import auth_cookie

pytestmark = pytest.mark.asyncio


async def _project(db_session, user, *, meta, chapters=None, front_matter=None) -> Project:
    project = Project(
        user_id=user.id, title="Compliance", meta=meta,
        front_matter=front_matter or [], chapters=chapters or [], works_cited=[],
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


async def test_no_profile_is_soft_ready(client: AsyncClient, db_session, user_a) -> None:
    project = await _project(db_session, user_a, meta={})
    response = await client.get(
        f"/projects/{project.id}/compliance", cookies=auth_cookie(user_a)
    )
    assert response.status_code == 200
    body = response.json()
    assert body["enforced"] is False
    assert body["ready"] is True


async def test_neurips_project_with_leaks_is_not_ready(client: AsyncClient, db_session, user_a) -> None:
    project = await _project(
        db_session, user_a,
        meta={"domain_profile": "neurips_paper"},
        chapters=[{"number": 1, "title": "Method", "blocks": [
            {"type": "paragraph", "runs": [{"text": "See https://github.com/me/repo"}]}
        ]}],
        front_matter=[{"kind": "acknowledgement", "body_blocks": [
            {"type": "paragraph", "runs": [{"text": "Thanks"}]}
        ]}],
    )
    response = await client.get(
        f"/projects/{project.id}/compliance", cookies=auth_cookie(user_a)
    )
    assert response.status_code == 200
    body = response.json()
    assert body["enforced"] is True
    assert body["ready"] is False
    codes = {f["code"] for f in body["findings"]}
    assert "deanonymizing_link" in codes
    assert "acknowledgement_present" in codes


async def test_compliance_is_owner_guarded(client: AsyncClient, db_session, user_a, user_b) -> None:
    project = await _project(db_session, user_a, meta={"domain_profile": "cvpr_paper"})
    response = await client.get(
        f"/projects/{project.id}/compliance", cookies=auth_cookie(user_b)
    )
    assert response.status_code == 404


async def test_detail_exposes_validators(client: AsyncClient, user_a) -> None:
    response = await client.get("/domain-profiles/neurips_paper", cookies=auth_cookie(user_a))
    assert response.status_code == 200
    body = response.json()
    assert body["enforced"] is True
    assert "page_budget" in body["validators"]
    assert body["page_limit"] == 9
