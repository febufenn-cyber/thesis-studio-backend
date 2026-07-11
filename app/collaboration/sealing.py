"""Immutable submission packages, attestations and external-review access."""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collaboration.workflow import canonical_checksum
from app.models.document_snapshot import DocumentSnapshot
from app.models.event import Event
from app.models.export import Export
from app.models.institutional_governance import ExternalReviewGrant, SubmissionPackage
from app.models.project import Project
from app.models.review_collaboration import ApprovalRecord, Attestation
from app.services.editor_service import create_snapshot


class SubmissionError(RuntimeError):
    pass


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _package_checksum(manifest: dict) -> str:
    raw = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


async def create_attestation(
    db: AsyncSession,
    project: Project,
    user_id: UUID,
    *,
    attestation_type: str,
    statement_version: str,
    statement_text: str,
    accepted: bool,
    submission_package_id: UUID | None = None,
    context: dict | None = None,
) -> Attestation:
    if not accepted:
        raise SubmissionError("A declined attestation cannot satisfy submission readiness.")
    row = Attestation(
        project_id=project.id,
        submission_package_id=submission_package_id,
        attestation_type=attestation_type,
        user_id=user_id,
        statement_version=statement_version,
        statement_text=statement_text,
        accepted=True,
        context=context or {"document_version": project.document_version},
    )
    db.add(row)
    db.add(
        Event(
            project_id=project.id,
            user_id=user_id,
            kind="workflow_attestation_recorded",
            data={"attestation_type": attestation_type, "statement_version": statement_version},
        )
    )
    await db.commit()
    await db.refresh(row)
    return row


async def submission_readiness(db: AsyncSession, project: Project) -> dict:
    policy = project.collaboration_policy or {}
    workflow = policy.get("workflow") if isinstance(policy.get("workflow"), dict) else policy
    required_dimensions = {"content", "citation", "formatting", "institutional"}
    if not workflow.get("format_review_required", True):
        required_dimensions.discard("formatting")
    if not workflow.get("institutional_approval_required", True):
        required_dimensions.discard("institutional")

    approvals = list(
        (
            await db.execute(
                select(ApprovalRecord).where(
                    ApprovalRecord.project_id == project.id,
                    ApprovalRecord.status == "active",
                    ApprovalRecord.dimension.in_(required_dimensions),
                )
            )
        ).scalars()
    )
    active_dimensions = {row.dimension for row in approvals}
    exports = list(
        (
            await db.execute(
                select(Export).where(
                    Export.project_id == project.id,
                    Export.status == "ready",
                    Export.document_version == project.document_version,
                )
            )
        ).scalars()
    )
    final_formats = {
        row.format
        for row in exports
        if (row.manifest or {}).get("state") == "final" and row.checksum and row.storage_key
    }
    attestations = list(
        (
            await db.execute(
                select(Attestation).where(
                    Attestation.project_id == project.id,
                    Attestation.submission_package_id.is_(None),
                    Attestation.accepted.is_(True),
                )
            )
        ).scalars()
    )
    attestation_types = {row.attestation_type for row in attestations}
    required_attestations = {"student_authorship"}
    if workflow.get("supervisor_approval_required", True):
        required_attestations.add("supervisor_workflow_approval")
    missing_approvals = sorted(required_dimensions - active_dimensions)
    missing_attestations = sorted(required_attestations - attestation_types)
    missing_formats = sorted({"docx", "pdf"} - final_formats)
    return {
        "ready": not missing_approvals and not missing_attestations and not missing_formats,
        "required_approval_dimensions": sorted(required_dimensions),
        "active_approval_dimensions": sorted(active_dimensions),
        "missing_approvals": missing_approvals,
        "required_attestations": sorted(required_attestations),
        "missing_attestations": missing_attestations,
        "final_formats": sorted(final_formats),
        "missing_final_formats": missing_formats,
        "document_version": project.document_version,
        "document_checksum": canonical_checksum(project),
    }


async def seal_submission(
    db: AsyncSession,
    project: Project,
    actor_id: UUID,
    *,
    note: str | None = None,
) -> SubmissionPackage:
    if project.submission_locked:
        raise SubmissionError("The current submission version is already sealed.")
    readiness = await submission_readiness(db, project)
    if not readiness["ready"]:
        raise SubmissionError(
            "Submission is not ready: "
            + "; ".join(
                filter(
                    None,
                    [
                        f"missing approvals {readiness['missing_approvals']}" if readiness["missing_approvals"] else "",
                        f"missing attestations {readiness['missing_attestations']}" if readiness["missing_attestations"] else "",
                        f"missing final formats {readiness['missing_final_formats']}" if readiness["missing_final_formats"] else "",
                    ],
                )
            )
        )
    snapshot = await create_snapshot(
        db,
        project,
        actor_id,
        name=f"Sealed submission v{project.document_version}",
        reason="submission_sealed",
        automatic=False,
    )
    approvals = list(
        (
            await db.execute(
                select(ApprovalRecord).where(
                    ApprovalRecord.project_id == project.id,
                    ApprovalRecord.status == "active",
                )
            )
        ).scalars()
    )
    exports = list(
        (
            await db.execute(
                select(Export).where(
                    Export.project_id == project.id,
                    Export.status == "ready",
                    Export.document_version == project.document_version,
                )
            )
        ).scalars()
    )
    attestations = list(
        (
            await db.execute(
                select(Attestation).where(
                    Attestation.project_id == project.id,
                    Attestation.submission_package_id.is_(None),
                    Attestation.accepted.is_(True),
                )
            )
        ).scalars()
    )
    package_number = int(
        (
            await db.execute(
                select(func.count(SubmissionPackage.id)).where(SubmissionPackage.project_id == project.id)
            )
        ).scalar_one()
    ) + 1
    manifest = {
        "schema": "robofox.submission-package.v1",
        "project_id": str(project.id),
        "package_number": package_number,
        "document_version": project.document_version,
        "document_checksum": snapshot.checksum,
        "snapshot_id": str(snapshot.id),
        "institution_id": str(project.institution_id),
        "department_id": str(project.department_id) if project.department_id else None,
        "profile_version_id": str(project.institutional_profile_version_id) if project.institutional_profile_version_id else None,
        "policy_version_id": str(project.institutional_policy_version_id) if project.institutional_policy_version_id else None,
        "approvals": [
            {
                "id": str(row.id),
                "dimension": row.dimension,
                "decision": row.decision,
                "scope_type": row.scope_type,
                "scope_id": str(row.scope_id) if row.scope_id else None,
                "approved_by": str(row.approved_by),
                "approved_at": row.approved_at.isoformat(),
                "checksum": row.document_checksum,
            }
            for row in approvals
        ],
        "exports": [
            {
                "id": str(row.id),
                "format": row.format,
                "checksum": row.checksum,
                "size_bytes": row.size_bytes,
                "storage_key": row.storage_key,
                "manifest": row.manifest or {},
            }
            for row in exports
        ],
        "attestations": [
            {
                "id": str(row.id),
                "type": row.attestation_type,
                "user_id": str(row.user_id),
                "statement_version": row.statement_version,
                "created_at": row.created_at.isoformat(),
            }
            for row in attestations
        ],
        "sealed_by": str(actor_id),
        "sealed_at": datetime.now(timezone.utc).isoformat(),
        "note": note,
        "signature_claim": "Authenticated workflow approval; not represented as a legal digital signature.",
    }
    row = SubmissionPackage(
        project_id=project.id,
        institution_id=project.institution_id,
        department_id=project.department_id,
        package_number=package_number,
        state="sealed",
        snapshot_id=snapshot.id,
        document_version=project.document_version,
        document_checksum=snapshot.checksum,
        profile_version_id=project.institutional_profile_version_id,
        policy_version_id=project.institutional_policy_version_id,
        export_ids=[str(item.id) for item in exports],
        approval_ids=[str(item.id) for item in approvals],
        manifest=manifest,
        package_checksum=_package_checksum(manifest),
        sealed_by=actor_id,
    )
    db.add(row)
    await db.flush()
    for attestation in attestations:
        attestation.submission_package_id = row.id
    project.submission_locked = True
    project.workflow_state = "submitted"
    db.add(
        Event(
            project_id=project.id,
            user_id=actor_id,
            kind="submission_package_sealed",
            data={
                "submission_package_id": str(row.id),
                "package_number": package_number,
                "package_checksum": row.package_checksum,
                "document_version": project.document_version,
            },
        )
    )
    await db.commit()
    await db.refresh(row)
    return row


async def withdraw_submission(
    db: AsyncSession,
    package: SubmissionPackage,
    project: Project,
    actor_id: UUID,
    reason: str,
) -> SubmissionPackage:
    if package.state != "sealed":
        raise SubmissionError("Only an active sealed package can be withdrawn.")
    package.state = "withdrawn"
    package.withdrawn_by = actor_id
    package.withdrawn_at = datetime.now(timezone.utc)
    package.withdrawal_reason = reason
    project.submission_locked = False
    project.workflow_state = "post_viva_corrections"
    db.add(
        Event(
            project_id=project.id,
            user_id=actor_id,
            kind="submission_package_withdrawn",
            data={"submission_package_id": str(package.id), "reason": reason},
        )
    )
    await db.commit()
    await db.refresh(package)
    return package


async def create_external_review_grant(
    db: AsyncSession,
    package: SubmissionPackage,
    actor_id: UUID,
    *,
    recipient_email: str,
    expires_at: datetime,
    permissions: list[str],
    download_allowed: bool,
    watermark: str | None,
) -> tuple[ExternalReviewGrant, str]:
    if package.state != "sealed":
        raise SubmissionError("External review can only target an active sealed package.")
    now = datetime.now(timezone.utc)
    if expires_at <= now:
        raise SubmissionError("External review expiry must be in the future.")
    allowed = {"sealed.read_metadata", "sealed.read_content", "sealed.download"}
    requested = set(permissions)
    if not requested or not requested.issubset(allowed):
        raise SubmissionError("Unsupported external-review permission set.")
    if "sealed.download" in requested and not download_allowed:
        raise SubmissionError("Download permission requires download_allowed=true.")
    token = secrets.token_urlsafe(32)
    row = ExternalReviewGrant(
        submission_package_id=package.id,
        recipient_email=recipient_email.strip().lower(),
        token_hash=_hash_token(token),
        permissions=sorted(requested),
        watermark=watermark,
        download_allowed=download_allowed,
        expires_at=expires_at,
        created_by=actor_id,
    )
    db.add(row)
    db.add(
        Event(
            project_id=package.project_id,
            user_id=actor_id,
            kind="external_review_access_created",
            data={
                "grant_id": str(row.id),
                "submission_package_id": str(package.id),
                "recipient_email_hash": hashlib.sha256(recipient_email.strip().lower().encode()).hexdigest(),
                "expires_at": expires_at.isoformat(),
                "permissions": sorted(requested),
            },
        )
    )
    await db.commit()
    await db.refresh(row)
    return row, token


async def resolve_external_review_grant(
    db: AsyncSession, token: str
) -> tuple[ExternalReviewGrant, SubmissionPackage, DocumentSnapshot]:
    now = datetime.now(timezone.utc)
    row = (
        await db.execute(
            select(ExternalReviewGrant).where(
                ExternalReviewGrant.token_hash == _hash_token(token),
                ExternalReviewGrant.status == "active",
                ExternalReviewGrant.expires_at > now,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise SubmissionError("External review access is invalid or expired.")
    package = (
        await db.execute(
            select(SubmissionPackage).where(
                SubmissionPackage.id == row.submission_package_id,
                SubmissionPackage.state == "sealed",
            )
        )
    ).scalar_one_or_none()
    if package is None:
        raise SubmissionError("The sealed submission is no longer available.")
    snapshot = (
        await db.execute(select(DocumentSnapshot).where(DocumentSnapshot.id == package.snapshot_id))
    ).scalar_one()
    row.last_accessed_at = now
    row.access_count += 1
    await db.commit()
    return row, package, snapshot


async def revoke_external_review_grant(
    db: AsyncSession, row: ExternalReviewGrant, actor_id: UUID
) -> None:
    row.status = "revoked"
    row.revoked_by = actor_id
    row.revoked_at = datetime.now(timezone.utc)
    await db.commit()
