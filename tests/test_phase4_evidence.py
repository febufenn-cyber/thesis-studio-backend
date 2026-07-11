"""Phase 4 source/quotation review capability tests."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.models.quote import Quote
from app.models.source import Source
from app.models.tenancy import OrganizationMembership, ProjectMembership
from app.models.user import User
from tests.conftest import auth_cookie


pytestmark = pytest.mark.asyncio


async def test_shared_registry_requires_separate_verification_capability(
    client: AsyncClient,
    db_session: AsyncSession,
    test_institution,
    user_a: User,
) -> None:
    created = await client.post(
        "/projects",
        json={"title": "Evidence Thesis", "mode": "student", "format_profile": "mla_strict"},
        cookies=auth_cookie(user_a),
    )
    project_id = created.json()["id"]
    project = (
        await db_session.execute(select(Project).where(Project.id == project_id))
    ).scalar_one()
    project.institution_id = test_institution.id

    supervisor = User(
        email=f"evidence-supervisor-{uuid4().hex[:6]}@test.edu",
        full_name="Evidence Supervisor",
        institution_id=test_institution.id,
        affiliation_status="domain_verified",
    )
    db_session.add(supervisor)
    await db_session.flush()
    db_session.add(
        OrganizationMembership(
            institution_id=test_institution.id,
            user_id=supervisor.id,
            role="supervisor",
            affiliation_status="admin_verified",
            status="active",
            verified_by=user_a.id,
            verified_at=datetime.now(timezone.utc),
        )
    )
    membership = ProjectMembership(
        project_id=project_id,
        user_id=supervisor.id,
        role="supervisor",
        capabilities=[],
        content_access=True,
        source_access=True,
        ai_history_access=False,
        granted_by=user_a.id,
    )
    db_session.add(membership)
    source = Source(
        project_id=project_id,
        user_id=user_a.id,
        kind="book",
        fields={"author": "Edward Said", "title": "Orientalism", "year": "1978"},
        raw_entry="Said, Edward. Orientalism. 1978.",
        parse_status="structured_with_review",
        identifiers={},
        verified=False,
    )
    db_session.add(source)
    await db_session.flush()
    quote = Quote(
        project_id=project_id,
        user_id=user_a.id,
        source_id=source.id,
        text="The exact registered quotation text.",
        locator="p. 42",
        verified=False,
    )
    db_session.add(quote)
    await db_session.commit()
    await db_session.refresh(supervisor)

    registry = await client.get(
        f"/projects/{project_id}/collaboration/evidence",
        cookies=auth_cookie(supervisor),
    )
    assert registry.status_code == 200
    assert registry.json()["verification_authority"] is False
    assert registry.json()["sources"][0]["id"] == str(source.id)

    denied = await client.post(
        f"/projects/{project_id}/collaboration/sources/{source.id}/verification",
        json={
            "verified": True,
            "method": "supervisor_review",
            "note": "Compared against the student's source copy.",
        },
        cookies=auth_cookie(supervisor),
    )
    assert denied.status_code == 404

    membership.capabilities = ["source.verify"]
    await db_session.commit()
    verified_source = await client.post(
        f"/projects/{project_id}/collaboration/sources/{source.id}/verification",
        json={
            "verified": True,
            "method": "supervisor_review",
            "note": "Compared against the student's source copy.",
        },
        cookies=auth_cookie(supervisor),
    )
    assert verified_source.status_code == 200
    assert verified_source.json()["verified"] is True

    verified_quote = await client.post(
        f"/projects/{project_id}/collaboration/quotes/{quote.id}/verification",
        json={
            "verified": True,
            "method": "manual_comparison",
            "note": "Exact wording and locator compared with the source copy.",
        },
        cookies=auth_cookie(supervisor),
    )
    assert verified_quote.status_code == 200
    assert verified_quote.json()["verified"] is True

    revoked_source = await client.post(
        f"/projects/{project_id}/collaboration/sources/{source.id}/verification",
        json={
            "verified": False,
            "method": "supervisor_review",
            "note": "The supplied edition no longer matches the registered metadata.",
        },
        cookies=auth_cookie(supervisor),
    )
    assert revoked_source.status_code == 200
    refreshed_quote = (
        await db_session.execute(select(Quote).where(Quote.id == quote.id))
    ).scalar_one()
    assert refreshed_quote.verified is False
