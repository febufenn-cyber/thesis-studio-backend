"""Phase 4 presence, data portability and metadata-only privacy tests."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.models.tenancy import Department, OrganizationMembership
from app.models.user import User
from tests.conftest import auth_cookie


pytestmark = pytest.mark.asyncio


async def test_presence_is_expiring_scoped_and_role_bounded(
    client: AsyncClient,
    db_session: AsyncSession,
    test_institution,
    user_a: User,
) -> None:
    created = await client.post(
        "/projects",
        json={"title": "Presence Thesis", "mode": "student", "format_profile": "mla_strict"},
        cookies=auth_cookie(user_a),
    )
    assert created.status_code == 201
    project_id = created.json()["id"]

    owner = await client.put(
        f"/projects/{project_id}/presence",
        json={
            "activity": "editing",
            "scope": {
                "type": "chapter",
                "chapter_id": str(uuid4()),
                "mode": "editor",
                "selected_text": "must never be stored",
                "prompt": "must never be stored",
            },
        },
        cookies=auth_cookie(user_a),
    )
    assert owner.status_code == 200
    assert owner.json()["activity"] == "editing"
    assert "selected_text" not in owner.json()["scope"]
    assert "prompt" not in owner.json()["scope"]
    assert owner.json()["live_cursors"] is False

    admin = User(
        email=f"presence-admin-{uuid4().hex[:6]}@test.edu",
        full_name="Presence Admin",
        institution_id=test_institution.id,
        affiliation_status="domain_verified",
    )
    db_session.add(admin)
    await db_session.flush()
    project = (
        await db_session.execute(select(Project).where(Project.id == project_id))
    ).scalar_one()
    project.institution_id = test_institution.id
    db_session.add(
        OrganizationMembership(
            institution_id=test_institution.id,
            user_id=admin.id,
            role="institution_admin",
            affiliation_status="admin_verified",
            status="active",
            verified_by=user_a.id,
            verified_at=datetime.now(timezone.utc),
        )
    )
    await db_session.commit()
    await db_session.refresh(admin)

    downgraded = await client.put(
        f"/projects/{project_id}/presence",
        json={"activity": "editing", "scope": {"type": "project", "mode": "collaboration"}},
        cookies=auth_cookie(admin),
    )
    assert downgraded.status_code == 200
    assert downgraded.json()["activity"] == "viewing"

    active = await client.get(
        f"/projects/{project_id}/presence",
        cookies=auth_cookie(admin),
    )
    assert active.status_code == 200
    roles = {row["role"] for row in active.json()}
    assert {"student", "institution_admin"}.issubset(roles)


async def test_project_export_respects_content_and_private_ai_boundaries(
    client: AsyncClient,
    db_session: AsyncSession,
    test_institution,
    user_a: User,
) -> None:
    created = await client.post(
        "/projects",
        json={"title": "Portable Thesis", "mode": "student", "format_profile": "mla_strict"},
        cookies=auth_cookie(user_a),
    )
    project_id = created.json()["id"]
    project = (
        await db_session.execute(select(Project).where(Project.id == project_id))
    ).scalar_one()
    project.institution_id = test_institution.id

    admin = User(
        email=f"portable-admin-{uuid4().hex[:6]}@test.edu",
        full_name="Portable Admin",
        institution_id=test_institution.id,
        affiliation_status="domain_verified",
    )
    db_session.add(admin)
    await db_session.flush()
    db_session.add(
        OrganizationMembership(
            institution_id=test_institution.id,
            user_id=admin.id,
            role="institution_admin",
            affiliation_status="admin_verified",
            status="active",
            verified_by=user_a.id,
            verified_at=datetime.now(timezone.utc),
        )
    )
    await db_session.commit()
    await db_session.refresh(admin)

    owner_export = await client.get(
        f"/projects/{project_id}/data-export?include_ai_history=true",
        cookies=auth_cookie(user_a),
    )
    assert owner_export.status_code == 200
    assert owner_export.json()["canonical_document"] is not None
    assert owner_export.json()["private_ai_history_included"] is True

    admin_export = await client.get(
        f"/projects/{project_id}/data-export?include_ai_history=true",
        cookies=auth_cookie(admin),
    )
    assert admin_export.status_code == 200
    assert admin_export.json()["canonical_document"] is None
    assert admin_export.json()["private_ai_history"] == []
    assert admin_export.json()["private_ai_history_included"] is False

    account_export = await client.get(
        "/account/data-export",
        cookies=auth_cookie(user_a),
    )
    assert account_export.status_code == 200
    assert account_export.json()["identity"]["email"] == user_a.email
    assert "retention_notice" in account_export.json()
