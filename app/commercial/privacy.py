"""Honest retention and deletion lifecycle execution.

Deletion first removes normal access, then storage objects, then active database data.
A minimal non-content audit record remains. Encrypted backup expiry is reported rather
than misrepresented as immediate erasure.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import delete, select

from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.models.ai_message import AIMessage
from app.models.ai_thread import AIThread
from app.models.commercial import ApplicationSession, DataLifecycleJob
from app.models.document_preview import DocumentPreview
from app.models.event import Event
from app.models.export import Export
from app.models.institutional_governance import RetentionPolicy, SubmissionPackage
from app.models.manuscript_revision import ManuscriptRevision
from app.models.project import Project
from app.models.tenancy import DataLifecycleRequest, OrganizationMembership, ProjectMembership
from app.models.user import User
from app.services.storage_service import get_storage_service


class LifecycleBlocked(RuntimeError):
    pass


def _hash_ids(values: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(values)).encode("utf-8")).hexdigest()


async def _retention_policy(db, institution_id: UUID) -> dict:
    row = (
        await db.execute(
            select(RetentionPolicy)
            .where(
                RetentionPolicy.institution_id == institution_id,
                RetentionPolicy.state == "published",
            )
            .order_by(RetentionPolicy.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return dict(row.policy or {}) if row else {
        "draft_retention_days": 365,
        "ai_chat_retention_days": 180,
        "preview_retention_days": 30,
        "sealed_submission_retention": "contract",
        "deletion_grace_days": get_settings().DELETION_GRACE_DAYS,
        "backup_expiry_days": 90,
    }


async def _project_storage_keys(db, project_id: UUID) -> list[tuple[str, str]]:
    keys: list[tuple[str, str]] = []
    revisions = list(
        (await db.execute(select(ManuscriptRevision).where(ManuscriptRevision.project_id == project_id))).scalars()
    )
    keys.extend(("original", row.storage_key) for row in revisions if row.storage_key)
    previews = list(
        (await db.execute(select(DocumentPreview).where(DocumentPreview.project_id == project_id))).scalars()
    )
    keys.extend(("preview", row.storage_key) for row in previews if row.storage_key)
    exports = list((await db.execute(select(Export).where(Export.project_id == project_id))).scalars())
    keys.extend(("export", row.storage_key) for row in exports if row.storage_key)
    return keys


async def _delete_keys(keys: list[tuple[str, str]]) -> tuple[int, list[dict]]:
    storage = get_storage_service()
    results: list[dict] = []
    deleted = 0
    for artifact_class, key in keys:
        try:
            await storage.delete(key)
        except Exception as exc:
            results.append({"class": artifact_class, "key_hash": hashlib.sha256(key.encode()).hexdigest(), "state": "failed", "error": type(exc).__name__})
        else:
            deleted += 1
            results.append({"class": artifact_class, "key_hash": hashlib.sha256(key.encode()).hexdigest(), "state": "deleted"})
    return deleted, results


async def execute_lifecycle_job(request_id: UUID) -> dict:
    async with AsyncSessionLocal() as db:
        request = (
            await db.execute(select(DataLifecycleRequest).where(DataLifecycleRequest.id == request_id))
        ).scalar_one_or_none()
        if request is None:
            raise LifecycleBlocked("Data lifecycle request no longer exists.")
        now = datetime.now(timezone.utc)
        if request.legal_hold:
            request.status = "blocked_legal_hold"
            request.result = {"message": "Deletion is blocked by a recorded legal or administrative hold."}
            await db.commit()
            return request.result
        if request.execute_after and request.execute_after > now:
            raise LifecycleBlocked("Deletion grace period has not elapsed.")
        request.status = "processing"
        await db.commit()

        if request.request_type in {"project_delete", "delete_project"}:
            if request.project_id is None:
                raise LifecycleBlocked("Project deletion request has no project target.")
            project = (
                await db.execute(select(Project).where(Project.id == request.project_id))
            ).scalar_one_or_none()
            if project is None:
                request.status = "completed"
                request.completed_at = now
                request.result = {"active_system": "already_absent"}
                await db.commit()
                return request.result
            sealed = (
                await db.execute(
                    select(SubmissionPackage.id).where(
                        SubmissionPackage.project_id == project.id,
                        SubmissionPackage.state == "sealed",
                    ).limit(1)
                )
            ).scalar_one_or_none()
            if sealed is not None:
                request.status = "authorization_required"
                request.result = {
                    "message": "A sealed institutional submission requires institutional authorization or withdrawal before deletion.",
                    "sealed_submission_present": True,
                }
                await db.commit()
                return request.result

            project.archived = True
            project.ai_enabled = False
            await db.commit()
            keys = await _project_storage_keys(db, project.id)
            job = DataLifecycleJob(
                request_id=request.id,
                stage="active_storage_delete",
                artifact_class="project_objects",
                state="running",
                object_count=len(keys),
                storage_references_hash=_hash_ids([key for _, key in keys]),
                started_at=now,
            )
            db.add(job)
            await db.commit()
            deleted, evidence = await _delete_keys(keys)
            failed = len(keys) - deleted
            job.deleted_count = deleted
            job.completed_at = datetime.now(timezone.utc)
            job.state = "completed" if failed == 0 else "partial"
            policy = await _retention_policy(db, request.institution_id)
            backup_days = int(policy.get("backup_expiry_days", 90))
            job.backup_expiry_note = (
                f"Encrypted backups may retain deleted data for up to {backup_days} days before scheduled expiry."
            )
            job.evidence = {"objects": evidence}
            if failed:
                request.status = "partial"
                request.result = {"deleted_objects": deleted, "failed_objects": failed, "retry_required": True}
                await db.commit()
                return request.result

            project_hash = hashlib.sha256(str(project.id).encode()).hexdigest()
            actor_id = request.user_id
            db.add(
                Event(
                    project_id=None,
                    user_id=actor_id,
                    kind="project_deletion_completed",
                    data={
                        "project_id_hash": project_hash,
                        "institution_id": str(request.institution_id),
                        "request_id": str(request.id),
                        "object_count": len(keys),
                        "backup_expiry_days": backup_days,
                    },
                )
            )
            await db.delete(project)
            request.project_id = None
            request.status = "completed"
            request.completed_at = datetime.now(timezone.utc)
            request.result = {
                "active_database": "deleted",
                "active_storage": "deleted",
                "objects_deleted": deleted,
                "backups": f"scheduled to expire within {backup_days} days",
                "permanent_deletion_claim": False,
            }
            await db.commit()
            return request.result

        if request.request_type in {"account_delete", "delete_account"}:
            user = (await db.execute(select(User).where(User.id == request.user_id))).scalar_one_or_none()
            if user is None:
                request.status = "completed"
                request.completed_at = now
                request.result = {"active_account": "already_absent"}
                await db.commit()
                return request.result
            sealed_count = int(
                (
                    await db.execute(
                        select(Project.id)
                        .join(SubmissionPackage, SubmissionPackage.project_id == Project.id)
                        .where(Project.user_id == user.id, SubmissionPackage.state == "sealed")
                    )
                ).scalars().unique().__len__()
            )
            if sealed_count:
                request.status = "authorization_required"
                request.result = {
                    "message": "Account erasure is blocked while sealed institutional submissions remain. Identity access can be suspended immediately.",
                    "sealed_project_count": sealed_count,
                }
                user.account_status = "suspended"
                await db.commit()
                return request.result
            await db.execute(
                ApplicationSession.__table__.update()
                .where(ApplicationSession.user_id == user.id, ApplicationSession.state == "active")
                .values(state="revoked", revoked_at=now, revoke_reason="Account deletion lifecycle started.")
            )
            await db.execute(
                OrganizationMembership.__table__.update()
                .where(OrganizationMembership.user_id == user.id)
                .values(status="revoked", suspended_at=now)
            )
            await db.execute(
                ProjectMembership.__table__.update()
                .where(ProjectMembership.user_id == user.id)
                .values(status="revoked", revoked_at=now, revoked_by=user.id)
            )
            await db.execute(delete(AIMessage).where(AIMessage.user_id == user.id))
            await db.execute(delete(AIThread).where(AIThread.user_id == user.id))
            user.email = f"deleted-{hashlib.sha256(str(user.id).encode()).hexdigest()[:20]}@invalid.local"
            user.full_name = None
            user.register_number = None
            user.account_status = "deleted"
            user.affiliation_status = "unaffiliated"
            request.status = "completed"
            request.completed_at = now
            request.result = {
                "identity": "anonymized",
                "sessions": "revoked",
                "private_ai_history": "deleted",
                "institutional_workflow_records": "retained without active account access",
                "backups": "expire according to documented backup retention",
                "permanent_deletion_claim": False,
            }
            await db.commit()
            return request.result

        if request.request_type in {"export", "data_export"}:
            request.status = "completed"
            request.completed_at = now
            request.result = {
                "message": "Use the authenticated project/account portability endpoints to generate the structured export.",
                "format": "JSON plus separately authenticated binary downloads",
            }
            await db.commit()
            return request.result
        raise LifecycleBlocked(f"Unsupported lifecycle request type: {request.request_type}")


async def execute_retention_sweep(payload: dict) -> dict:
    now = datetime.now(timezone.utc)
    institution_id = UUID(str(payload["institution_id"])) if payload.get("institution_id") else None
    deleted_previews = 0
    deleted_ai_messages = 0
    storage = get_storage_service()
    async with AsyncSessionLocal() as db:
        institutions = [institution_id] if institution_id else list(
            (await db.execute(select(RetentionPolicy.institution_id).distinct())).scalars()
        )
        for tenant_id in institutions:
            policy = await _retention_policy(db, tenant_id)
            preview_days = int(policy.get("preview_retention_days", 30))
            ai_days = int(policy.get("ai_chat_retention_days", 180))
            preview_rows = list(
                (
                    await db.execute(
                        select(DocumentPreview)
                        .join(Project, Project.id == DocumentPreview.project_id)
                        .where(
                            Project.institution_id == tenant_id,
                            DocumentPreview.created_at < now - timedelta(days=preview_days),
                        )
                    )
                ).scalars()
            )
            for row in preview_rows:
                if row.storage_key:
                    try:
                        await storage.delete(row.storage_key)
                    except Exception:
                        continue
                await db.delete(row)
                deleted_previews += 1
            old_threads = select(AIThread.id).join(Project, Project.id == AIThread.project_id).where(
                Project.institution_id == tenant_id,
                AIThread.created_at < now - timedelta(days=ai_days),
            )
            result = await db.execute(delete(AIMessage).where(AIMessage.thread_id.in_(old_threads)))
            deleted_ai_messages += int(result.rowcount or 0)
        await db.commit()
    return {
        "deleted_previews": deleted_previews,
        "deleted_ai_messages": deleted_ai_messages,
        "executed_at": now.isoformat(),
        "sealed_submissions_untouched": True,
    }
