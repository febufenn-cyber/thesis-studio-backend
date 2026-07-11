"""Phase 4 tenant isolation, invitation, revocation and capability API tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.institution import Institution
from app.models.project import Project
from app.models.tenancy import Department, OrganizationMembership, ProjectMembership
from app.models.user import User
from tests.conftest import auth_cookie


pytestmark = pytest.mark.asyncio


async def _user(
    db: AsyncSession,
    institution: Institution,
    name: str,
) -> User:
    row = User(
        email=f"{name.lower().replace(' ', '-')}-{uuid4().hex[:6]}@example.edu",
        full_name=name,
        institution_id=institution.id,
        affiliation_status="domain_verified",
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def _institution(db: AsyncSession, suffix: str) -> Institution:
    row = Institution(
        name=f"{suffix} University",
        short_name=suffix,
        email_domains=f"{suffix.lower()}.edu",
        address="Campus Road",
        short_address="Campus",
        university_name=f"{suffix} University",
        default_department="English",
        department_aided=False,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def _project(
    client: AsyncClient,
    db: AsyncSession,
    student: User,
    institution: Institution,
    department: Department,
) -> dict:
    created = await client.post(
        "/projects",
        json={"title": "Collaborative Thesis", "format_profile": "mla_strict", "mode": "student"},
        cookies=auth_cookie(student),
    )
    assert created.status_code == 201
    data = created.json()
    project = (
        await db.execute(select(Project).where(Project.id == data["id"]))
    ).scalar_one()
    project.institution_id = institution.id
    project.department_id = department.id
    project.workflow_state = "student_review"
    await db.commit()
    seeded = await client.patch(
        f"/projects/{project.id}/chapters",
        json={
            "expected_version": project.document_version,
            "chapters": [
                {
                    "number": 1,
                    "title": "Introduction",
                    "status": "in_progress",
                    "blocks": [
                        {
                            "type": "paragraph",
                            "runs": [{"text": "The house records institutional memory."}],
                        }
                    ],
                }
            ],
        },
        cookies=auth_cookie(student),
    )
    assert seeded.status_code == 200
    return seeded.json()


async def _org_member(
    db: AsyncSession,
    institution: Institution,
    user: User,
    role: str,
    department: Department | None = None,
    *,
    affiliation_status: str = "admin_verified",
) -> OrganizationMembership:
    row = OrganizationMembership(
        institution_id=institution.id,
        department_id=department.id if department else None,
        user_id=user.id,
        role=role,
        affiliation_status=affiliation_status,
        status="active",
        verified_by=user.id,
        verified_at=datetime.now(timezone.utc),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def _project_member(
    db: AsyncSession,
    project_id,
    user: User,
    role: str,
    grantor: User,
    *,
    content: bool = True,
    sources: bool = True,
    ai_history: bool = False,
    capabilities: list[str] | None = None,
) -> ProjectMembership:
    row = ProjectMembership(
        project_id=project_id,
        user_id=user.id,
        role=role,
        capabilities=capabilities or [],
        content_access=content,
        source_access=sources,
        ai_history_access=ai_history,
        granted_by=grantor.id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def test_verified_project_membership_and_admin_metadata_are_separate(
    client: AsyncClient,
    db_session: AsyncSession,
    test_institution: Institution,
    user_a: User,
) -> None:
    department = Department(
        institution_id=test_institution.id,
        name="Department of English",
        code="ENG",
        created_by=user_a.id,
    )
    db_session.add(department)
    await db_session.commit()
    await db_session.refresh(department)
    project = await _project(client, db_session, user_a, test_institution, department)

    supervisor = await _user(db_session, test_institution, "Dr Supervisor")
    admin = await _user(db_session, test_institution, "Department Admin")
    await _org_member(db_session, test_institution, supervisor, "supervisor", department)
    await _org_member(db_session, test_institution, admin, "department_admin", department)
    await _project_member(db_session, project["id"], supervisor, "supervisor", user_a)

    supervisor_access = await client.get(
        f"/projects/{project['id']}/collaboration/access",
        cookies=auth_cookie(supervisor),
    )
    assert supervisor_access.status_code == 200
    assert supervisor_access.json()["content_access"] is True
    assert supervisor_access.json()["ai_history_access"] is False
    assert "project.approve_academic" in supervisor_access.json()["capabilities"]
    assert "project.edit_content" not in supervisor_access.json()["capabilities"]

    admin_access = await client.get(
        f"/projects/{project['id']}/collaboration/access",
        cookies=auth_cookie(admin),
    )
    assert admin_access.status_code == 200
    assert admin_access.json()["content_access"] is False
    assert admin_access.json()["ai_history_access"] is False

    # Operational metadata is available, manuscript review content remains opaque.
    projects = await client.get("/collaboration/projects", cookies=auth_cookie(admin))
    assert projects.status_code == 200
    assert project["id"] in {row["id"] for row in projects.json()}
    content = await client.get(
        f"/projects/{project['id']}/review-cycles",
        cookies=auth_cookie(admin),
    )
    assert content.status_code == 404


async def test_unverified_revoked_and_cross_tenant_access_remain_opaque(
    client: AsyncClient,
    db_session: AsyncSession,
    test_institution: Institution,
    user_a: User,
) -> None:
    department = Department(
        institution_id=test_institution.id,
        name="English Studies",
        code="ES",
        created_by=user_a.id,
    )
    db_session.add(department)
    await db_session.commit()
    await db_session.refresh(department)
    project = await _project(client, db_session, user_a, test_institution, department)

    invited = await _user(db_session, test_institution, "Unverified Reviewer")
    await _org_member(
        db_session,
        test_institution,
        invited,
        "supervisor",
        department,
        affiliation_status="invited",
    )
    membership = await _project_member(db_session, project["id"], invited, "supervisor", user_a)
    denied = await client.get(
        f"/projects/{project['id']}/collaboration/access",
        cookies=auth_cookie(invited),
    )
    assert denied.status_code == 404

    org = (
        await db_session.execute(
            select(OrganizationMembership).where(
                OrganizationMembership.user_id == invited.id,
                OrganizationMembership.institution_id == test_institution.id,
            )
        )
    ).scalar_one()
    org.affiliation_status = "admin_verified"
    await db_session.commit()
    allowed = await client.get(
        f"/projects/{project['id']}/collaboration/access",
        cookies=auth_cookie(invited),
    )
    assert allowed.status_code == 200

    membership.status = "revoked"
    membership.revoked_at = datetime.now(timezone.utc)
    await db_session.commit()
    revoked = await client.get(
        f"/projects/{project['id']}/collaboration/access",
        cookies=auth_cookie(invited),
    )
    assert revoked.status_code == 404

    other_institution = await _institution(db_session, "OTHER")
    outsider = await _user(db_session, other_institution, "Outside Supervisor")
    await _org_member(db_session, other_institution, outsider, "institution_admin")
    cross_tenant = await client.get(
        f"/projects/{project['id']}/collaboration/access",
        cookies=auth_cookie(outsider),
    )
    assert cross_tenant.status_code == 404


async def test_department_admin_cannot_cross_department_or_self_approve(
    client: AsyncClient,
    db_session: AsyncSession,
    test_institution: Institution,
    user_a: User,
) -> None:
    english = Department(
        institution_id=test_institution.id,
        name="English Department",
        code="EN",
        created_by=user_a.id,
    )
    history = Department(
        institution_id=test_institution.id,
        name="History Department",
        code="HI",
        created_by=user_a.id,
    )
    db_session.add_all([english, history])
    await db_session.commit()
    await db_session.refresh(english)
    await db_session.refresh(history)
    project = await _project(client, db_session, user_a, test_institution, english)

    history_admin = await _user(db_session, test_institution, "History Admin")
    await _org_member(db_session, test_institution, history_admin, "department_admin", history)
    denied = await client.get(
        f"/projects/{project['id']}/collaboration/access",
        cookies=auth_cookie(history_admin),
    )
    assert denied.status_code == 404

    self_approval = await client.post(
        f"/projects/{project['id']}/approvals",
        json={
            "dimension": "content",
            "scope_type": "project",
            "decision": "approved",
            "note": "I approve my own work",
        },
        cookies=auth_cookie(user_a),
    )
    assert self_approval.status_code in {404, 409}


async def test_invitation_is_email_bound_and_revocable(
    client: AsyncClient,
    db_session: AsyncSession,
    test_institution: Institution,
    user_a: User,
    user_b: User,
) -> None:
    department = Department(
        institution_id=test_institution.id,
        name="Invitation Department",
        code="INV",
        created_by=user_a.id,
    )
    db_session.add(department)
    await db_session.commit()
    await db_session.refresh(department)
    project = await _project(client, db_session, user_a, test_institution, department)
    supervisor = await _user(db_session, test_institution, "Invited Supervisor")

    invite = await client.post(
        f"/institutions/{test_institution.id}/invitations",
        json={
            "email": supervisor.email,
            "role": "supervisor",
            "department_id": str(department.id),
            "project_id": project["id"],
            "expires_in_days": 3,
        },
        cookies=auth_cookie(user_a),
    )
    assert invite.status_code == 201
    token = invite.json()["invitation_token"]

    wrong_user = await client.post(
        "/collaboration/invitations/accept",
        json={"token": token},
        cookies=auth_cookie(user_b),
    )
    assert wrong_user.status_code == 404

    accepted = await client.post(
        "/collaboration/invitations/accept",
        json={"token": token},
        cookies=auth_cookie(supervisor),
    )
    assert accepted.status_code == 200
    assert accepted.json()["role"] == "supervisor"

    access = await client.get(
        f"/projects/{project['id']}/collaboration/access",
        cookies=auth_cookie(supervisor),
    )
    assert access.status_code == 200
    assert access.json()["ai_history_access"] is False
