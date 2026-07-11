"""Phase 5 reliability, privacy lifecycle, support and recovery tests."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.commercial.privacy import execute_lifecycle_job
from app.commercial.recovery import (
    complete_restore_drill,
    register_backup,
    start_restore_drill,
)
from app.commercial.support import diagnostic_bundle
from app.models.commercial import RecoveryPolicy
from app.models.job import Job
from app.models.project import Project
from app.models.tenancy import DataLifecycleRequest
from app.models.user import User
from app.services.job_queue import _recover_expired_leases


pytestmark = pytest.mark.asyncio


async def test_expired_worker_lease_is_requeued_without_losing_payload(
    db_session: AsyncSession,
    user_a: User,
) -> None:
    job = Job(
        kind="export",
        queue_name="pdf",
        priority=10,
        user_id=user_a.id,
        payload={"export_id": str(uuid4())},
        status="running",
        attempts=1,
        max_attempts=3,
        available_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        locked_by="dead-worker",
        locked_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        heartbeat_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        idempotency_key=f"lease-test-{uuid4()}",
    )
    db_session.add(job)
    await db_session.commit()
    recovered = await _recover_expired_leases(db_session, datetime.now(timezone.utc))
    assert recovered == 1
    assert job.status == "queued"
    assert job.locked_by is None
    assert job.payload["export_id"]


async def test_restore_drill_requires_matching_checksum(
    db_session: AsyncSession,
    user_a: User,
    test_institution,
) -> None:
    policy = RecoveryPolicy(
        institution_id=test_institution.id,
        artifact_class="sealed_submission",
        rpo_minutes=15,
        rto_minutes=120,
        durable=True,
        backup_method="encrypted object storage snapshot",
        restore_runbook="Restore into an isolated environment, validate schema and compare sealed checksums.",
        created_by=user_a.id,
    )
    db_session.add(policy)
    await db_session.flush()
    backup = await register_backup(
        db_session,
        policy,
        scope="sealed/submission/1",
        storage_reference="backup://phase5/test",
        checksum="a" * 64,
        encrypted=True,
    )
    drill = await start_restore_drill(
        db_session,
        backup,
        target_environment="isolated-restore",
        actor_id=user_a.id,
    )
    await complete_restore_drill(
        db_session,
        drill,
        restored_checksum="a" * 64,
        evidence={"database_restored": True, "objects_resolved": True},
    )
    assert drill.state == "passed"
    failed = await start_restore_drill(
        db_session,
        backup,
        target_environment="isolated-restore-2",
        actor_id=user_a.id,
    )
    await complete_restore_drill(
        db_session,
        failed,
        restored_checksum="b" * 64,
        evidence={"database_restored": True},
    )
    assert failed.state == "failed"


async def test_support_diagnostic_never_contains_thesis_text(
    db_session: AsyncSession,
    user_a: User,
    test_institution,
) -> None:
    project = Project(
        user_id=user_a.id,
        institution_id=test_institution.id,
        title="Sensitive Thesis Title",
        meta={"abstract": "DO-NOT-LEAK-ABSTRACT"},
        chapters=[{"title": "Secret chapter", "blocks": [{"text": "DO-NOT-LEAK-PROSE"}]}],
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    bundle = await diagnostic_bundle(
        db_session,
        project,
        support_user_id=user_a.id,
        justification="Investigate a failed export without reading manuscript content.",
    )
    serialized = json.dumps(bundle, default=str)
    assert "DO-NOT-LEAK-ABSTRACT" not in serialized
    assert "DO-NOT-LEAK-PROSE" not in serialized
    assert bundle["privacy"]["manuscript_content_included"] is False


async def test_draft_deletion_removes_active_project_but_keeps_honest_audit(
    db_session: AsyncSession,
    user_a: User,
    test_institution,
    monkeypatch,
) -> None:
    project = Project(
        user_id=user_a.id,
        institution_id=test_institution.id,
        title="Draft scheduled for deletion",
        meta={"title": "Draft scheduled for deletion"},
    )
    db_session.add(project)
    await db_session.flush()
    request = DataLifecycleRequest(
        institution_id=test_institution.id,
        user_id=user_a.id,
        project_id=project.id,
        request_type="project_delete",
        status="grace_period",
        reason="Student requested deletion after exporting their work.",
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
    assert result["active_database"] == "deleted"
    assert result["permanent_deletion_claim"] is False
    assert (await db_session.execute(select(Project).where(Project.id == project.id))).scalar_one_or_none() is None
