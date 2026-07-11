"""Phase 4 institutional profile, policy, template and onboarding API tests."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.models.tenancy import OrganizationMembership
from app.models.user import User
from tests.conftest import auth_cookie


pytestmark = pytest.mark.asyncio


async def test_institutional_versions_stage_publish_and_gate_onboarding(
    client: AsyncClient,
    db_session: AsyncSession,
    test_institution,
    user_a: User,
) -> None:
    admin = User(
        email=f"institution-admin-{uuid4().hex[:6]}@test.edu",
        full_name="Institution Administrator",
        institution_id=test_institution.id,
        affiliation_status="domain_verified",
    )
    db_session.add(admin)
    await db_session.flush()
    now = datetime.now(timezone.utc)
    db_session.add_all(
        [
            OrganizationMembership(
                institution_id=test_institution.id,
                user_id=admin.id,
                role="institution_admin",
                affiliation_status="admin_verified",
                status="active",
                verified_by=admin.id,
                verified_at=now,
            ),
            OrganizationMembership(
                institution_id=test_institution.id,
                user_id=user_a.id,
                role="student",
                affiliation_status="admin_verified",
                status="active",
                verified_by=admin.id,
                verified_at=now,
            ),
        ]
    )
    await db_session.commit()
    await db_session.refresh(admin)

    department = await client.post(
        f"/institutions/{test_institution.id}/departments",
        json={"name": "Department of English", "code": "ENG"},
        cookies=auth_cookie(admin),
    )
    assert department.status_code == 201

    policy = await client.post(
        f"/institutions/{test_institution.id}/policies",
        json={
            "label": "MA English 2026 policy",
            "policy": {
                "ai_policy": {
                    "coaching": True,
                    "rewrite_proposals": True,
                    "full_section_generation": False,
                    "disclosure_required": True,
                },
                "privacy": {"admin_content_access_default": False},
            },
        },
        cookies=auth_cookie(admin),
    )
    assert policy.status_code == 201
    staged_policy = await client.post(
        f"/institutions/{test_institution.id}/policies/{policy.json()['id']}/state",
        json={"target": "staging"},
        cookies=auth_cookie(admin),
    )
    assert staged_policy.status_code == 200
    published_policy = await client.post(
        f"/institutions/{test_institution.id}/policies/{policy.json()['id']}/state",
        json={"target": "published"},
        cookies=auth_cookie(admin),
    )
    assert published_policy.status_code == 200

    profile = await client.post(
        f"/institutions/{test_institution.id}/profiles",
        json={
            "programme": "MA English",
            "academic_year": "2026-2027",
            "label": "MA English dissertation",
            "base_profile": "mla_strict",
            "profile_data": {"margin_left": 1.5, "line_spacing": 2.0},
            "required_front_matter": ["title_page", "certificate", "declaration"],
            "locked_template_ids": [],
        },
        cookies=auth_cookie(admin),
    )
    assert profile.status_code == 201
    assert profile.json()["state"] == "draft"
    staged_profile = await client.post(
        f"/institutions/{test_institution.id}/profiles/{profile.json()['id']}/state",
        json={"target": "staging"},
        cookies=auth_cookie(admin),
    )
    assert staged_profile.status_code == 200
    published_profile = await client.post(
        f"/institutions/{test_institution.id}/profiles/{profile.json()['id']}/state",
        json={"target": "published"},
        cookies=auth_cookie(admin),
    )
    assert published_profile.status_code == 200

    template = await client.post(
        f"/institutions/{test_institution.id}/templates",
        json={
            "template_kind": "certificate",
            "body": "This is to certify that the dissertation is the student's work.",
            "structured": {"locked": True},
            "academic_note": "Workflow wording only; signature remains physical or separately certified.",
        },
        cookies=auth_cookie(admin),
    )
    assert template.status_code == 201
    for target in ("under_review", "approved", "published"):
        transition = await client.post(
            f"/institutions/{test_institution.id}/templates/{template.json()['id']}/state",
            json={"target": target},
            cookies=auth_cookie(admin),
        )
        assert transition.status_code == 200

    project = await client.post(
        "/projects",
        json={"title": "Institution Pilot", "mode": "student", "format_profile": "mla_strict"},
        cookies=auth_cookie(user_a),
    )
    assert project.status_code == 201
    project_row = (
        await db_session.execute(select(Project).where(Project.id == project.json()["id"]))
    ).scalar_one()
    project_row.institution_id = test_institution.id
    await db_session.commit()

    readiness = await client.get(
        f"/institutions/{test_institution.id}/onboarding",
        cookies=auth_cookie(admin),
    )
    assert readiness.status_code == 200
    assert readiness.json()["production_ready"] is True
    assert all(readiness.json()["checklist"].values())

    impact = await client.get(
        f"/institutions/{test_institution.id}/profiles/{profile.json()['id']}/impact",
        cookies=auth_cookie(admin),
    )
    assert impact.status_code == 200
    assert impact.json()["automatic_upgrade"] is False
