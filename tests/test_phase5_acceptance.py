"""End-to-end Phase 5 commercial reliability acceptance demonstration."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.capacity import health_snapshot
from app.commercial.billing import ingest_webhook
from app.commercial.entitlements import EntitlementContext, resolve_entitlement
from app.commercial.recovery import complete_restore_drill, register_backup, start_restore_drill
from app.commercial.sessions import issue_session, revoke_all_sessions, validate_session, SessionInvalid
from app.commercial.support import diagnostic_bundle, retry_job
from app.core.config import get_settings
from app.models.ai_run import AIRun
from app.models.ai_thread import AIThread
from app.models.commercial import (
    AIProvider,
    AIProviderHealth,
    EditionVersion,
    ProductEdition,
    RecoveryPolicy,
)
from app.models.export import Export
from app.models.job import Job
from app.models.project import Project
from app.models.user import User
from app.services.job_queue import _recover_expired_leases


pytestmark = pytest.mark.asyncio


def _signed_event(envelope: dict) -> tuple[bytes, str]:
    raw = json.dumps(envelope, separators=(",", ":")).encode()
    timestamp = int(datetime.now(timezone.utc).timestamp())
    digest = hmac.new(
        get_settings().BILLING_WEBHOOK_SECRET.encode(),
        f"{timestamp}.".encode() + raw,
        hashlib.sha256,
    ).hexdigest()
    return raw, f"t={timestamp},v1={digest}"


async def test_commercial_readiness_survives_provider_and_worker_failure(
    db_session: AsyncSession,
    test_institution,
    user_a: User,
) -> None:
    # 1–3. A signed annual institutional purchase provisions value-based entitlements.
    edition = ProductEdition(
        slug=f"acceptance-institution-{uuid4().hex[:8]}",
        audience="institution",
        name="Institution Annual Acceptance",
        state="published",
    )
    db_session.add(edition)
    await db_session.flush()
    edition_version = EditionVersion(
        edition_id=edition.id,
        version=1,
        label="Annual acceptance contract",
        currency="INR",
        billing_interval="year",
        list_price_minor=500_000,
        entitlements={
            "project.create": True,
            "project.active_limit": 500,
            "ai.chat": True,
            "ai.chapter_review.monthly": 100,
            "ai.whole_thesis_review.monthly": 20,
            "export.docx": True,
            "export.pdf": True,
            "export.pdf.monthly": 1000,
            "review.supervisor": True,
            "seat.student_limit": 500,
            "seat.staff_limit": 100,
            "retention.days": 1825,
        },
        state="published",
        effective_from=datetime.now(timezone.utc),
        created_by=user_a.id,
        published_by=user_a.id,
        published_at=datetime.now(timezone.utc),
    )
    db_session.add(edition_version)
    await db_session.commit()
    envelope = {
        "id": f"evt_{uuid4().hex}",
        "type": "subscription.updated",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "data": {
            "customer_id": f"cus_{uuid4().hex}",
            "subscription_id": f"sub_{uuid4().hex}",
            "institution_id": str(test_institution.id),
            "actor_user_id": str(user_a.id),
            "edition_slug": edition.slug,
            "edition_version": 1,
            "state": "active",
            "current_period_start": datetime.now(timezone.utc).isoformat(),
            "current_period_end": (datetime.now(timezone.utc) + timedelta(days=365)).isoformat(),
        },
    }
    raw, signature = _signed_event(envelope)
    event, created = await ingest_webhook(db_session, "test", raw, signature)
    assert created is True and event.state == "processed"
    entitlement = await resolve_entitlement(
        db_session,
        EntitlementContext(institution_id=test_institution.id, user_id=None),
        "export.pdf",
    )
    assert entitlement.value is True
    assert entitlement.source == "edition:active"

    project = Project(
        user_id=user_a.id,
        institution_id=test_institution.id,
        title="Commercial readiness thesis",
        meta={"title": "Commercial readiness thesis"},
    )
    db_session.add(project)
    await db_session.flush()

    # 4–6. One AI provider opens its circuit; the application/edit/export boundary stays healthy.
    provider = AIProvider(
        slug=f"acceptance-provider-{uuid4().hex[:8]}",
        adapter="http_json",
        institution_id=test_institution.id,
        credential_reference="env:NONEXISTENT_ACCEPTANCE_SECRET",
        supported_tasks=["understand"],
        model_routes={"understand": "test-model"},
        state="active",
        max_concurrency=2,
        created_by=user_a.id,
    )
    db_session.add(provider)
    await db_session.flush()
    db_session.add(
        AIProviderHealth(
            provider_id=provider.id,
            circuit_state="open",
            consecutive_failures=5,
            opened_at=datetime.now(timezone.utc),
            retry_after=datetime.now(timezone.utc) + timedelta(minutes=5),
            last_failure_at=datetime.now(timezone.utc),
            last_error_class="ProviderRateLimit",
        )
    )
    thread = AIThread(project_id=project.id, user_id=user_a.id, title="Private", private=True)
    db_session.add(thread)
    await db_session.flush()
    db_session.add(
        AIRun(
            project_id=project.id,
            thread_id=thread.id,
            user_id=user_a.id,
            task_mode="understand",
            result_type="conversation",
            risk_level="low",
            scope={"type": "project"},
            status="queued",
            requested_document_version=project.document_version,
            prompt_name="understand",
            prompt_version="1",
            model="test-model",
            provider_id=provider.id,
            provider_slug=provider.slug,
            provider_adapter=provider.adapter,
            context_manifest={},
            progress={"message": "Waiting for healthy provider capacity."},
        )
    )
    await db_session.commit()
    health = await health_snapshot(db_session, project, user_a.id)
    assert health["component_health"]["application"] == "operational"
    assert health["component_health"]["editing"] == "operational"
    assert health["component_health"]["export"] == "operational"
    assert health["component_health"]["ai"] == "degraded"

    # 7–10. A dead PDF worker lease is reclaimed without losing the operation payload.
    export = Export(
        project_id=project.id,
        user_id=user_a.id,
        format="pdf",
        document_version=project.document_version,
        profile_version="institutional:1",
        status="failed",
        error_message="Worker process terminated.",
        manifest={"state": "review"},
    )
    db_session.add(export)
    await db_session.flush()
    pdf_job = Job(
        kind="export",
        queue_name="pdf",
        priority=10,
        project_id=project.id,
        user_id=user_a.id,
        payload={"export_id": str(export.id), "project_id": str(project.id), "user_id": str(user_a.id)},
        status="running",
        attempts=1,
        max_attempts=3,
        available_at=datetime.now(timezone.utc) - timedelta(minutes=2),
        locked_by="crashed-pdf-worker",
        locked_at=datetime.now(timezone.utc) - timedelta(minutes=2),
        heartbeat_at=datetime.now(timezone.utc) - timedelta(minutes=2),
        lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        idempotency_key=f"acceptance-export:{export.id}",
    )
    db_session.add(pdf_job)
    await db_session.commit()
    assert await _recover_expired_leases(db_session, datetime.now(timezone.utc)) == 1
    assert pdf_job.status == "queued"
    assert pdf_job.payload["export_id"] == str(export.id)

    # 11. A former staff member loses every server-side session immediately.
    former_staff = User(
        email=f"former-{uuid4().hex[:8]}@test.edu",
        full_name="Former Staff",
        institution_id=test_institution.id,
        affiliation_status="admin_verified",
    )
    db_session.add(former_staff)
    await db_session.flush()
    session, token = await issue_session(db_session, former_staff, auth_method="test")
    await db_session.commit()
    assert await revoke_all_sessions(
        db_session,
        former_staff.id,
        actor_id=user_a.id,
        reason="Employment ended and institution access was revoked.",
    ) == 1
    await db_session.commit()
    with pytest.raises(SessionInvalid):
        await validate_session(
            db_session,
            user_id=former_staff.id,
            session_id=session.id,
            token=token,
            touch=False,
        )

    # 12–15. Backup evidence only passes when the restored checksum matches.
    policy = RecoveryPolicy(
        institution_id=test_institution.id,
        artifact_class="sealed_submission",
        rpo_minutes=15,
        rto_minutes=120,
        durable=True,
        backup_method="encrypted database and object snapshot",
        restore_runbook="Restore into isolation, run migrations, resolve object references and compare the sealed checksum.",
        created_by=user_a.id,
    )
    db_session.add(policy)
    await db_session.flush()
    backup = await register_backup(
        db_session,
        policy,
        scope="institution/database-and-sealed-objects",
        storage_reference="backup://acceptance/snapshot",
        checksum="c" * 64,
        encrypted=True,
    )
    drill = await start_restore_drill(
        db_session,
        backup,
        target_environment="restore-drill",
        actor_id=user_a.id,
    )
    await complete_restore_drill(
        db_session,
        drill,
        restored_checksum="c" * 64,
        evidence={"schema_restored": True, "membership_links_restored": True, "sealed_checksums_checked": True},
    )
    assert drill.state == "passed"
    assert drill.expected_checksum == drill.restored_checksum

    # 16–18. Support can diagnose and retry the failed export without seeing thesis content.
    project.meta = {"abstract": "PRIVATE ACCEPTANCE ABSTRACT"}
    project.chapters = [{"title": "Private", "blocks": [{"text": "PRIVATE ACCEPTANCE PROSE"}]}]
    await db_session.commit()
    bundle = await diagnostic_bundle(
        db_session,
        project,
        support_user_id=user_a.id,
        justification="Resolve failed PDF conversion from metadata and worker state only.",
    )
    serialized = json.dumps(bundle, default=str)
    assert "PRIVATE ACCEPTANCE ABSTRACT" not in serialized
    assert "PRIVATE ACCEPTANCE PROSE" not in serialized
    pdf_job.status = "failed"
    pdf_job.error_message = "Worker terminated"
    await retry_job(
        db_session,
        pdf_job,
        support_user_id=user_a.id,
        justification="Requeue idempotent PDF job after worker replacement.",
    )
    assert pdf_job.status == "queued"
    assert bundle["privacy"]["manuscript_content_included"] is False
