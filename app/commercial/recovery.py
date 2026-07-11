"""Recovery policies, backup evidence and checksum-preserving restore drills."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.commercial import BackupRecord, RecoveryPolicy, RestoreDrill
from app.models.event import Event
from app.models.institutional_governance import SubmissionPackage


class RecoveryError(RuntimeError):
    pass


def canonical_digest(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


async def register_backup(
    db: AsyncSession,
    policy: RecoveryPolicy,
    *,
    scope: str,
    storage_reference: str,
    checksum: str,
    encrypted: bool,
    metadata: dict | None = None,
) -> BackupRecord:
    if policy.durable and not encrypted:
        raise RecoveryError("Durable backups must be encrypted before registration.")
    row = BackupRecord(
        policy_id=policy.id,
        scope=scope,
        storage_reference=storage_reference,
        encrypted=encrypted,
        checksum=checksum,
        state="created",
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        metadata_json=metadata or {},
    )
    db.add(row)
    await db.flush()
    return row


async def start_restore_drill(
    db: AsyncSession,
    backup: BackupRecord,
    *,
    target_environment: str,
    actor_id: UUID,
    expected_checksum: str | None = None,
) -> RestoreDrill:
    if backup.state not in {"created", "verified"}:
        raise RecoveryError("Only completed backups can enter a restore drill.")
    row = RestoreDrill(
        backup_id=backup.id,
        target_environment=target_environment,
        state="running",
        expected_checksum=expected_checksum or backup.checksum,
        started_at=datetime.now(timezone.utc),
        performed_by=actor_id,
    )
    db.add(row)
    await db.flush()
    return row


async def complete_restore_drill(
    db: AsyncSession,
    drill: RestoreDrill,
    *,
    restored_checksum: str,
    evidence: dict,
) -> RestoreDrill:
    if drill.state != "running":
        raise RecoveryError("Restore drill is not running.")
    now = datetime.now(timezone.utc)
    drill.restored_checksum = restored_checksum
    drill.completed_at = now
    drill.duration_seconds = max(0, int((now - drill.started_at).total_seconds())) if drill.started_at else None
    drill.evidence = evidence
    drill.state = "passed" if restored_checksum == drill.expected_checksum else "failed"
    return drill


async def verify_sealed_submission_restore(
    db: AsyncSession,
    package_id: UUID,
    *,
    restored_package_manifest: dict,
) -> dict:
    package = (
        await db.execute(select(SubmissionPackage).where(SubmissionPackage.id == package_id))
    ).scalar_one_or_none()
    if package is None:
        raise RecoveryError("Sealed submission package not found.")
    expected_package_checksum = package.package_checksum
    restored_manifest_checksum = canonical_digest(restored_package_manifest)
    manifest_claim = str(restored_package_manifest.get("package_checksum") or restored_manifest_checksum)
    document_checksum = str(restored_package_manifest.get("document_checksum") or "")
    passed = (
        manifest_claim == expected_package_checksum
        and document_checksum == package.document_checksum
    )
    return {
        "package_id": package.id,
        "expected_package_checksum": expected_package_checksum,
        "restored_package_checksum": manifest_claim,
        "expected_document_checksum": package.document_checksum,
        "restored_document_checksum": document_checksum,
        "manifest_digest": restored_manifest_checksum,
        "passed": passed,
    }


async def record_recovery_event(
    db: AsyncSession,
    *,
    actor_id: UUID,
    drill: RestoreDrill,
    institution_id: UUID | None,
) -> None:
    db.add(
        Event(
            project_id=None,
            user_id=actor_id,
            kind="restore_drill_completed",
            data={
                "restore_drill_id": str(drill.id),
                "backup_id": str(drill.backup_id),
                "institution_id": str(institution_id) if institution_id else None,
                "state": drill.state,
                "duration_seconds": drill.duration_seconds,
                "checksum_match": drill.expected_checksum == drill.restored_checksum,
            },
        )
    )
