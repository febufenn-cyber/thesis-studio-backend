"""Public API keys — bearer auth on existing endpoints (MF6)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.models.project import Project
from tests.conftest import auth_cookie

pytestmark = pytest.mark.asyncio


async def _project(db_session, user) -> Project:
    project = Project(user_id=user.id, title="K", meta={"title": "Keyed"}, front_matter=[],
                      chapters=[{"number": 1, "title": "C", "blocks": [
                          {"type": "paragraph", "runs": [{"text": "hi"}]}]}], works_cited=[])
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


async def test_create_returns_plaintext_once(client: AsyncClient, user_a) -> None:
    created = await client.post(
        "/api-keys", json={"label": "cli", "scopes": ["export"]}, cookies=auth_cookie(user_a)
    )
    assert created.status_code == 201
    body = created.json()
    assert body["key"].startswith("ak_")
    assert body["scopes"] == ["export"]

    # Listing never reveals the plaintext.
    listed = await client.get("/api-keys", cookies=auth_cookie(user_a))
    assert listed.status_code == 200
    entry = listed.json()["api_keys"][0]
    assert "key" not in entry
    assert entry["prefix"].startswith("ak_")


async def test_bearer_key_authenticates_existing_endpoint(client: AsyncClient, db_session, user_a) -> None:
    project = await _project(db_session, user_a)
    key = (await client.post("/api-keys", json={"scopes": ["export"]}, cookies=auth_cookie(user_a))).json()["key"]

    # Use the key (no cookie) on a real endpoint (Phase 5 interchange export).
    response = await client.get(
        f"/v1/projects/{project.id}/export/latex",
        headers={"Authorization": f"Bearer {key}"},
    )
    assert response.status_code == 200
    assert "\\documentclass" in response.json()["content"]


async def test_revoked_key_is_401(client: AsyncClient, db_session, user_a) -> None:
    project = await _project(db_session, user_a)
    created = (await client.post("/api-keys", json={"scopes": ["export"]}, cookies=auth_cookie(user_a))).json()
    key, key_id = created["key"], created["id"]

    revoke = await client.delete(f"/api-keys/{key_id}", cookies=auth_cookie(user_a))
    assert revoke.status_code == 200

    response = await client.get(
        f"/v1/projects/{project.id}/export/latex",
        headers={"Authorization": f"Bearer {key}"},
    )
    assert response.status_code == 401


async def test_unknown_scope_rejected(client: AsyncClient, user_a) -> None:
    response = await client.post(
        "/api-keys", json={"scopes": ["superuser"]}, cookies=auth_cookie(user_a)
    )
    assert response.status_code == 422


async def test_bearer_key_still_owner_guarded(client: AsyncClient, db_session, user_a, user_b) -> None:
    project = await _project(db_session, user_a)
    # user_b's key cannot reach user_a's project (owner guard unchanged -> 404).
    key = (await client.post("/api-keys", json={"scopes": ["export"]}, cookies=auth_cookie(user_b))).json()["key"]
    response = await client.get(
        f"/v1/projects/{project.id}/export/latex",
        headers={"Authorization": f"Bearer {key}"},
    )
    assert response.status_code == 404


async def test_scopes_are_enforced_default_deny(client: AsyncClient, db_session, user_a) -> None:
    """A key may do only what its scopes grant (fail-closed)."""
    project = await _project(db_session, user_a)
    # export-only key: GET export works (above), but arbitrary reads are denied...
    exp_key = (await client.post("/api-keys", json={"scopes": ["export"]},
                                 cookies=auth_cookie(user_a))).json()["key"]
    denied = await client.get("/v1/projects", headers={"Authorization": f"Bearer {exp_key}"})
    assert denied.status_code == 403
    # ...and imports are denied too.
    denied = await client.post(
        f"/v1/projects/{project.id}/references/import",
        json={"format": "bibtex", "content": "@book{k, title={T}}"},
        headers={"Authorization": f"Bearer {exp_key}"},
    )
    assert denied.status_code == 403

    # read-only key: GETs work, mutations are denied.
    read_key = (await client.post("/api-keys", json={"scopes": ["read"]},
                                  cookies=auth_cookie(user_a))).json()["key"]
    ok = await client.get("/v1/projects", headers={"Authorization": f"Bearer {read_key}"})
    assert ok.status_code == 200
    denied = await client.post(
        f"/v1/projects/{project.id}/references/import",
        json={"format": "bibtex", "content": "@book{k, title={T}}"},
        headers={"Authorization": f"Bearer {read_key}"},
    )
    assert denied.status_code == 403

    # import-scoped key can import.
    imp_key = (await client.post("/api-keys", json={"scopes": ["import"]},
                                 cookies=auth_cookie(user_a))).json()["key"]
    ok = await client.post(
        f"/v1/projects/{project.id}/references/import",
        json={"format": "bibtex", "content": "@book{k2, title={T2}, author={A, B}, year={2020}}"},
        headers={"Authorization": f"Bearer {imp_key}"},
    )
    assert ok.status_code == 200


async def test_keys_can_never_manage_keys(client: AsyncClient, user_a) -> None:
    """API-key management is session-only, regardless of scopes."""
    key = (await client.post("/api-keys", json={"scopes": ["read", "export", "resolve", "import"]},
                             cookies=auth_cookie(user_a))).json()["key"]
    listed = await client.get("/v1/api-keys", headers={"Authorization": f"Bearer {key}"})
    assert listed.status_code == 403
    minted = await client.post("/v1/api-keys", json={"scopes": ["read"]},
                               headers={"Authorization": f"Bearer {key}"})
    assert minted.status_code == 403
