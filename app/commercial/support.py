"""Audited support operations that default to metadata-only access."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.commercial.observability import release_identity
from app.models.ai_run import AIRun
from app.models.commercial import ApplicationSession, SupportAction
from app.models.document_preview import DocumentPreview
from app.models.export import Export
from app.models.job import Job
from app.models.manuscript_revision import ManuscriptRevision
from app.models.project import Project
from app.models.review_collaboration import ApprovalRecord, ReviewCycle


class SupportError(RuntimeError):
    pass


async def diagnostic_bundle(
    db: AsyncSession,
    project: Project,
    *,
    support_user_id: UUID,
    justification: str,
) -> dict:
    """Return operational state without manuscript text, quotations or private AI prompts."""
    jobs = list(
        (
            await db.execute(
                select(Job)
                .where(Job.project_id == project.id)
                .order_by(Job.created_at.desc())
                .limit(50)
            )
        ).scalars()
    )
    exports = list(
        (
            await db.execute(
                select(Export)
                .where(Export.project_id == project.id)
                .order_by(Export.created_at.desc())
                .limit(25)
            )
        ).scalars()
    )
    previews = list(
        (
            await db.execute(
                select(DocumentPreview)
                .where(DocumentPreview.project_id == project.id)
                .order_by(DocumentPreview.created_at.desc())
                .limit(25)
            )
        ).scalars()
    )
    revisions = list(
        (
            await db.execute(
                select(ManuscriptRevision)
                .where(ManuscriptRevision.project_id == project.id)
                .order_by(ManuscriptRevision.revision_number.desc())
                .limit(25)
            )
        ).scalars()
    )
    ai_counts = {
        state: int(
            (
                await db.execute(
                    select(func.count(AIRun.id)).where(
                        AIRun.project_id == project.id,
                        AIRun.status == state,
                    )
                )
            ).scalar_one()
        )
        for state in ("queued", "running", "succeeded", "failed", "cancelled", "stale")
    }
    review_count = int(
        (
            await db.execute(select(func.count(ReviewCycle.id)).where(ReviewCycle.project_id == project.id))
        ).scalar_one()
    )
    approval_count = int(
        (
            await db.execute(select(func.count(ApprovalRecord.id)).where(ApprovalRecord.project_id == project.id))
        ).scalar_one()
    )
    bundle = {
        "schema": "robofox.support-diagnostic.v1",
        "generated_at": datetime.now(timezone.utc),
        "release": release_identity(),
        "project": {
            "id": project.id,
            "institution_id": project.institution_id,
            "department_id": project.department_id,
            "workflow_state": project.workflow_state,
            "document_version": project.document_version,
            "canonical_schema_version": project.canonical_schema_version,
            "active_revision_id": project.active_revision_id,
            "format_profile": project.format_profile,
            "institutional_profile_version_id": project.institutional_profile_version_id,
            "institutional_policy_version_id": project.institutional_policy_version_id,
            "submission_locked": project.submission_locked,
            "archived": project.archived,
            "created_at": project.created_at,
            "updated_at": project.updated_at,
        },
        "jobs": [
            {
                "id": row.id,
                "kind": row.kind,
                "queue": row.queue_name,
                "status": row.status,
                "attempts": row.attempts,
                "max_attempts": row.max_attempts,
                "available_at": row.available_at,
                "deadline_at": row.deadline_at,
                "locked_by": row.locked_by,
                "heartbeat_at": row.heartbeat_at,
                "lease_expires_at": row.lease_expires_at,
                "error_class_present": bool(row.error_message),
                "release_sha": row.release_sha,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }
            for row in jobs
        ],
        "exports": [
            {
                "id": row.id,
                "format": row.format,
                "document_version": row.document_version,
                "profile_version": row.profile_version,
                "status": row.status,
                "checksum": row.checksum,
                "size_bytes": row.size_bytes,
                "has_storage_object": bool(row.storage_key),
                "created_at": row.created_at,
            }
            for row in exports
        ],
        "previews": [
            {
                "id": row.id,
                "document_version": row.document_version,
                "profile_version": row.profile_version,
                "status": row.status,
                "checksum": row.checksum,
                "page_count": row.page_count,
                "has_storage_object": bool(row.storage_key),
                "created_at": row.created_at,
            }
            for row in previews
        ],
        "revisions": [
            {
                "id": row.id,
                "revision_number": row.revision_number,
                "mime_type": row.mime_type,
                "size_bytes": row.size_bytes,
                "checksum": row.checksum,
                "parser_version": row.parser_version,
                "canonical_schema_version": row.canonical_schema_version,
                "status": row.status,
                "applied": row.applied,
                "created_at": row.created_at,
            }
            for row in revisions
        ],
        "ai_run_counts": ai_counts,
        "review_cycle_count": review_count,
        "approval_record_count": approval_count,
        "privacy": {
            "manuscript_content_included": False,
            "source_or_quote_content_included": False,
            "private_ai_content_included": False,
            "full_email_included": False,
        },
    }
    db.add(
        SupportAction(
            support_user_id=support_user_id,
            institution_id=project.institution_id,
            project_id=project.id,
            action="generate_diagnostic_bundle",
            justification=justification,
            content_accessed=False,
            result={"job_count": len(jobs), "export_count": len(exports), "preview_count": len(previews)},
            release_sha=release_identity()["release_sha"],
        )
    )
    await db.flush()
    return bundle


async def retry_job(
    db: AsyncSession,
    job: Job,
    *,
    support_user_id: UUID,
    justification: str,
) -> Job:
    if job.status not in {"failed", "cancelled"}:
        raise SupportError("Only failed or cancelled jobs can be retried by support.")
    if job.attempts >= job.max_attempts:
        job.max_attempts = job.attempts + 1
    job.status = "queued"
    job.available_at = datetime.now(timezone.utc)
    job.locked_at = None
    job.locked_by = None
    job.lease_expires_at = None
    job.error_message = None
    db.add(
        SupportAction(
            support_user_id=support_user_id,
            project_id=job.project_id,
            action="retry_failed_job",
            justification=justification,
            content_accessed=False,
            result={"job_id": str(job.id), "kind": job.kind, "queue": job.queue_name},
            release_sha=release_identity()["release_sha"],
        )
    )
    await db.flush()
    return job
