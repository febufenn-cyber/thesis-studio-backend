"""API tests for the DomainProfiles catalog and readiness endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import auth_cookie

pytestmark = pytest.mark.asyncio


async def test_list_domain_profiles(client: AsyncClient, user_a) -> None:
    response = await client.get("/domain-profiles", cookies=auth_cookie(user_a))
    assert response.status_code == 200
    profiles = response.json()["profiles"]
    assert len(profiles) >= 8
    keys = {p["key"] for p in profiles}
    assert "phd_thesis" in keys and "ma_dissertation" in keys
    for p in profiles:
        assert {"key", "label", "credential", "default_citation_style"} <= p.keys()


async def test_domain_profile_detail_phd_thesis(client: AsyncClient, user_a) -> None:
    response = await client.get("/domain-profiles/phd_thesis", cookies=auth_cookie(user_a))
    assert response.status_code == 200
    body = response.json()
    assert body["key"] == "phd_thesis"
    assert body["default_citation_style"] == "chicago-ad-17"
    section_names = {s["name"] for s in body["sections"]}
    assert "declaration_of_ai_use" in section_names
    chapters_spec = next(s for s in body["sections"] if s["name"] == "chapters")
    assert chapters_spec["repeatable"] is True
    assert body["submission_checklist"]


async def test_domain_profile_detail_unknown_is_404(client: AsyncClient, user_a) -> None:
    response = await client.get("/domain-profiles/not_a_real_profile", cookies=auth_cookie(user_a))
    assert response.status_code == 404


async def test_readiness_without_domain_profile_is_ready(client: AsyncClient, user_a) -> None:
    cookies = auth_cookie(user_a)
    created = await client.post("/projects", json={"title": "Profile-less project"}, cookies=cookies)
    assert created.status_code == 201
    project = created.json()
    response = await client.get(f"/projects/{project['id']}/domain-readiness", cookies=cookies)
    assert response.status_code == 200
    body = response.json()
    assert body["profile"] is None
    assert body["ready"] is True
    assert body["missing_sections"] == []
