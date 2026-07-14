"""Research consent + transparency API (docs/LLD.md 3.8)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.models.project import Project
from tests.conftest import auth_cookie

pytestmark = pytest.mark.asyncio
_TERMS = "2026-07"


async def test_consent_grant_list_revoke(client: AsyncClient, user_a) -> None:
    granted = await client.post(
        "/research/consent",
        json={"scope": "revision_history", "terms_version": _TERMS},
        cookies=auth_cookie(user_a),
    )
    assert granted.status_code == 201

    listing = await client.get("/research/consent", cookies=auth_cookie(user_a))
    assert listing.status_code == 200
    scopes = {c["scope"]: c for c in listing.json()["consents"]}
    assert scopes["revision_history"]["revoked_at"] is None

    revoked = await client.delete("/research/consent/revision_history", cookies=auth_cookie(user_a))
    assert revoked.status_code == 200
    assert revoked.json()["revoked"] == 1


async def test_consent_wrong_terms_is_409(client: AsyncClient, user_a) -> None:
    response = await client.post(
        "/research/consent",
        json={"scope": "revision_history", "terms_version": "wrong"},
        cookies=auth_cookie(user_a),
    )
    assert response.status_code == 409


async def test_shared_preview_has_no_pii(client: AsyncClient, db_session, user_a) -> None:
    project = Project(
        user_id=user_a.id, title="Secret Title", meta={"candidate": {"name": "Jane Secret"}, "citation_style": "mla-9"},
        front_matter=[], chapters=[{"number": 1, "title": "C", "blocks": [
            {"type": "paragraph", "origin": "human", "runs": [{"text": "SECRET body"}]}
        ]}], works_cited=[],
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    response = await client.get(
        f"/projects/{project.id}/research/shared", cookies=auth_cookie(user_a)
    )
    assert response.status_code == 200
    blob = str(response.json())
    assert "Jane Secret" not in blob
    assert "SECRET body" not in blob
    assert response.json()["shared"]["origin_counts"] == {"human": 1}


async def test_shared_is_owner_guarded(client: AsyncClient, db_session, user_a, user_b) -> None:
    project = Project(user_id=user_a.id, title="X", meta={}, front_matter=[], chapters=[], works_cited=[])
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    response = await client.get(
        f"/projects/{project.id}/research/shared", cookies=auth_cookie(user_b)
    )
    assert response.status_code == 404
