"""Locale API (docs/LLD.md 3.7)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.models.project import Project
from tests.conftest import auth_cookie

pytestmark = pytest.mark.asyncio


async def _project(db_session, user) -> Project:
    project = Project(user_id=user.id, title="L", meta={}, front_matter=[], chapters=[], works_cited=[])
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


async def test_list_locales(client: AsyncClient, user_a) -> None:
    response = await client.get("/locales", cookies=auth_cookie(user_a))
    assert response.status_code == 200
    tags = {loc["tag"] for loc in response.json()["locales"]}
    assert {"ar", "de-DE", "zh-Hans"} <= tags


async def test_set_project_locale(client: AsyncClient, db_session, user_a) -> None:
    project = await _project(db_session, user_a)
    response = await client.patch(
        f"/projects/{project.id}/locale",
        json={"locale": "ar", "name_script": "both"},
        cookies=auth_cookie(user_a),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["locale"] == "ar"
    assert body["name_script"] == "both"
    await db_session.refresh(project)
    assert project.meta["locale"] == "ar"


async def test_unknown_locale_is_422(client: AsyncClient, db_session, user_a) -> None:
    project = await _project(db_session, user_a)
    response = await client.patch(
        f"/projects/{project.id}/locale",
        json={"locale": "xx-YY"},
        cookies=auth_cookie(user_a),
    )
    assert response.status_code == 422


async def test_locale_is_owner_guarded(client: AsyncClient, db_session, user_a, user_b) -> None:
    project = await _project(db_session, user_a)
    response = await client.patch(
        f"/projects/{project.id}/locale",
        json={"locale": "fr-FR"},
        cookies=auth_cookie(user_b),
    )
    assert response.status_code == 404
