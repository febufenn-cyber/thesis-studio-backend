"""Domain-profile wiring into project creation."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import auth_cookie

pytestmark = pytest.mark.asyncio


async def test_domain_profile_sets_citation_style_and_key(client: AsyncClient, user_a) -> None:
    created = await client.post(
        "/projects",
        json={
            "title": "Doctoral Study",
            "mode": "operator",
            "doc_type": "phd_thesis",
            "format_profile": "tn_university",
            "domain_profile": "phd_thesis",
        },
        cookies=auth_cookie(user_a),
    )
    assert created.status_code == 201
    project_id = created.json()["id"]

    fetched = await client.get(f"/projects/{project_id}", cookies=auth_cookie(user_a))
    assert fetched.status_code == 200
    meta = fetched.json()["meta"]
    assert meta["citation_style"] == "chicago-ad-17"
    assert meta["domain_profile"] == "phd_thesis"


async def test_project_without_domain_profile_keeps_default(client: AsyncClient, user_a) -> None:
    created = await client.post(
        "/projects", json={"title": "Plain Project"}, cookies=auth_cookie(user_a)
    )
    assert created.status_code == 201
    project_id = created.json()["id"]
    fetched = await client.get(f"/projects/{project_id}", cookies=auth_cookie(user_a))
    assert fetched.status_code == 200
    # No domain profile -> no citation-style/domain seeding, but the submission
    # title is defaulted from the project title (FRICTION_LOG F4) so readiness
    # isn't blocked by an invisibly-empty title field.
    assert fetched.json()["meta"] == {"title": "Plain Project"}


async def test_unknown_domain_profile_is_rejected(client: AsyncClient, user_a) -> None:
    response = await client.post(
        "/projects",
        json={"title": "Bad Profile", "domain_profile": "not_a_real_profile"},
        cookies=auth_cookie(user_a),
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "Unknown domain profile"
