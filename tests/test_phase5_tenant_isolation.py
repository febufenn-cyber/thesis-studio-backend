"""Adversarial Phase 5 commercial tenant and custody boundaries."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.commercial.billing import ingest_webhook
from app.commercial.privacy import execute_lifecycle_job
from app.commercial.sessions import issue_session
from app.core.config import get_settings
from app.models.commercial import BillingEvent
from app.models.institution import Institution
from app.models.institutional_governance import SubmissionPackage
from app.models.project import Project
from app.models.tenancy import DataLifecycleRequest, OrganizationMembership
from app.models.user import User


pytestmark = pytest.mark.asyncio


def _signed(envelope: dict) -> tuple[bytes, str]:
    raw = json.dumps(envelope, separators=(",", ":")).encode()
    timestamp = int(datetime.now(timezone.utc).timestamp())
    signature = hmac.new(
        get_settings().BILLING_WEBHOOK_SECRET.encode(),
        f"{timestamp}.".encode() + raw,
        hashlib.sha256,
    ).hexdigest()
    return raw, f"t={timestamp},v1={signature}"


async def _institution_admin(
    db: AsyncSession,
    institution: Institution,
    email_prefix: str,
) -> tuple[User, dict[str, str]]:
    user = User(
        email=f"{email_prefix}-{uuid4().hex[:8]}@test.edu",
        full_name=f"{email_prefix} admin",
        institution_id=institution.id,
        affiliation_status="admin_verified",
    )
    db.add(user)
    await db.flush()
    db.add(
        OrganizationMembership(
            institution_id=institution.id,
            user_id=user.id,
            role="institution_admin",
            affiliation_status="admin_verified",
            status="active",
            verified_by=user.id,
            verified_at=datetime.now(timezone.utc),
        )
    )
    _, token = await issue_session(db, user, auth_method="test")
    await db.commit()
    return user, {get_settings().SESSION_COOKIE_NAME: token}


async def test_institution_cannot_replay_another_tenants_billing_event(
    client: AsyncClient,
    db_session: AsyncSession,
    test_institution: Institution,
    user_a: User,
) -> None:
    other = Institution(
        name="Other University",
        short_name=f"OU-{uuid4().hex[:6]}",
        email_domains=["other.test"],
        is_active=True,
    )
    db_session.add(other)
    await db_session.commit()
    other_admin, other_cookies = await _institution_admin(db_session, other, "other")
    _, owner_cookies = await _institution_admin(db_session, test_institution, "owner")

    envelope = {
        "id": f"evt_{uuid4().hex}",
        "type": "customer.updated",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "data": {
            "customer_id": f"cus_{uuid4().hex}",
            "institution_id": str(test_institution.id),
            "actor_user_id": str(user_a.id),
            "state": "active",
        },
    }
    raw, signature = _signed(envelope)
    event, _ = await ingest_webhook(db_session, "test", raw, signature)
    assert event.state == "processed"

    denied = await client.post(
        f"/institutions/{other.id}/commercial/billing-events/{event.id}/replay",
        cookies=other_cookies,
    )
    assert denied.status_code == 404

    allowed = await client.post(
        f"/institutions/{test_institution.id}/commercial/billing-events/{event.id}/replay",
        cookies=owner_cookies,
    )
    assert allowed.status_code == 200
    stored = (
        await db_session.execute(select(BillingEvent).where(BillingEvent.id == event.id))
    ).scalar_one()
    assert stored.attempts >= 2


async def test_sealed_submission_blocks_destructive_project_deletion(
    db_session: AsyncSession,
    test_institution: Institution,
    user_a: User,
    monkeypatch,
) -> None:
    project = Project(
        user_id=user_a.id,
        institution_id=test_institution.id,
        title="Sealed custody test",
        meta={"title": "Sealed custody test"},
        submission_locked=True,
    )
    db_session.add(project)
    await db_session.flush()
    package = SubmissionPackage(
        project_id=project.id,
        institution_id=test_institution.id,
        package_number=1,
        state="sealed",
        document_version=project.document_version,
        document_checksum="a" * 64,
        package_checksum="b" * 64,
        manifest={"state": "sealed"},
        sealed_by=user_a.id,
        sealed_at=datetime.now(timezone.utc),
    )
    db_session.add(package)
    request = DataLifecycleRequest(
        institution_id=test_institution.id,
        user_id=user_a.id,
        project_id=project.id,
        request_type="project_delete",
        status="grace_period",
        reason="Student requests deletion after submission.",
        execute_after=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    db_session.add(request)
    await db_session.commit()

    class SameSession:
        async def __aenter__(self):
            return db_session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    import app.commercial.privacy as privacy

    monkeypatch.setattr(privacy, "AsyncSessionLocal", lambda: SameSession())
    result = await execute_lifecycle_job(request.id)
    assert result["sealed_submission_present"] is True
    assert result["normal_access_removed"] is True
    assert result["permanent_deletion_claim"] is False
    assert request.status == "authorization_required"
    assert project.archived is True
    assert (
        await db_session.execute(select(Project).where(Project.id == project.id))
    ).scalar_one_or_none() is not None
