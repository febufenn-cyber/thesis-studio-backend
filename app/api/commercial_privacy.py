"""Privacy notices, data inventory, consent and honest lifecycle requests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentApplicationSession, CurrentUser
from app.collaboration.capabilities import require_institution_capability, require_project_capability
from app.commercial.sessions import require_recent_reauthentication
from app.core.config import get_settings
from app.db.deps import get_db
from app.models.commercial import (
    ConsentRecord,
    DataInventoryRecord,
    PrivacyNoticeVersion,
    ProcessingPurpose,
    SubprocessorRecord,
)
from app.models.institutional_governance import RetentionPolicy, SubmissionPackage
from app.models.tenancy import DataLifecycleRequest
from app.services.job_queue import enqueue_job


router = APIRouter(tags=["commercial-privacy"])


class LifecycleRequestCreate(BaseModel):
    request_type: str = Field(..., pattern=r"^(project_delete|account_delete|data_export)$")
    project_id: UUID | None = None
    reason: str = Field(..., min_length=5, max_length=8000)


class ConsentCreate(BaseModel):
    notice_version_id: UUID
    purpose_key: str = Field(..., min_length=2, max_length=100)
    decision: str = Field(..., pattern=r"^(accepted|declined)$")
    source: str = Field("web", min_length=2, max_length=30)
    evidence: dict = Field(default_factory=dict)


class PrivacyNoticeCreate(BaseModel):
    audience: str = Field(..., min_length=2, max_length=40)
    jurisdiction: str = Field("IN", min_length=2, max_length=40)
    body: str = Field(..., min_length=50, max_length=100000)
    purposes: list[str] = Field(default_factory=list, max_length=100)


class DataInventoryCreate(BaseModel):
    data_category: str = Field(..., min_length=2, max_length=100)
    purpose_key: str = Field(..., min_length=2, max_length=100)
    subject_owner: str = Field(..., min_length=2, max_length=80)
    storage_system: str = Field(..., min_length=2, max_length=120)
    retention_rule: dict
    shared_with: list[str] = Field(default_factory=list, max_length=100)
    deletion_path: str = Field(..., min_length=10, max_length=10000)
    durable_class: str = Field(..., min_length=2, max_length=60)


async def _grace_days(db: AsyncSession, institution_id: UUID) -> int:
    row = (
        await db.execute(
            select(RetentionPolicy)
            .where(RetentionPolicy.institution_id == institution_id, RetentionPolicy.state == "published")
            .order_by(RetentionPolicy.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return int((row.policy or {}).get("deletion_grace_days", get_settings().DELETION_GRACE_DAYS)) if row else get_settings().DELETION_GRACE_DAYS


@router.post("/privacy/lifecycle-requests", status_code=202)
async def create_lifecycle_request(
    body: LifecycleRequestCreate,
    current_user: CurrentUser,
    current_session: CurrentApplicationSession,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_recent_reauthentication(current_session)
    institution_id = current_user.institution_id
    if body.request_type == "project_delete":
        if body.project_id is None:
            raise HTTPException(status_code=422, detail="project_id is required for project deletion")
        access = await require_project_capability(db, body.project_id, current_user, "data.request_deletion_self")
        if access.project.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="Project not found")
        institution_id = access.project.institution_id or institution_id
    elif body.project_id is not None:
        raise HTTPException(status_code=422, detail="project_id is only valid for project deletion")

    duplicate = (
        await db.execute(
            select(DataLifecycleRequest).where(
                DataLifecycleRequest.user_id == current_user.id,
                DataLifecycleRequest.request_type == body.request_type,
                DataLifecycleRequest.project_id == body.project_id,
                DataLifecycleRequest.status.in_({"requested", "grace_period", "processing", "partial"}),
            )
        )
    ).scalar_one_or_none()
    if duplicate:
        return {"id": duplicate.id, "status": duplicate.status, "execute_after": duplicate.execute_after, "duplicate": True}

    grace = await _grace_days(db, institution_id)
    row = DataLifecycleRequest(
        institution_id=institution_id,
        user_id=current_user.id,
        project_id=body.project_id,
        request_type=body.request_type,
        status="completed" if body.request_type == "data_export" else "grace_period",
        reason=body.reason,
        execute_after=(datetime.now(timezone.utc) + timedelta(days=grace)) if body.request_type != "data_export" else None,
        result={
            "active_access": "scheduled for removal" if body.request_type != "data_export" else "use authenticated export endpoint",
            "backup_expiry": "separate documented schedule",
            "permanent_deletion_claim": False,
        },
    )
    if body.request_type == "data_export":
        row.completed_at = datetime.now(timezone.utc)
    db.add(row)
    await db.flush()
    if body.request_type != "data_export":
        await enqueue_job(
            db,
            kind="data_lifecycle",
            queue_name="maintenance",
            user_id=current_user.id,
            project_id=body.project_id,
            payload={"request_id": str(row.id)},
            available_at if False else None,
        )
    await db.commit()
    return {"id": row.id, "status": row.status, "execute_after": row.execute_after, "deletion_is_immediate": False}


@router.get("/privacy/lifecycle-requests")
async def list_lifecycle_requests(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    rows = list((await db.execute(select(DataLifecycleRequest).where(DataLifecycleRequest.user_id == current_user.id).order_by(DataLifecycleRequest.requested_at.desc()))).scalars())
    return [{"id": row.id, "request_type": row.request_type, "project_id": row.project_id, "status": row.status, "legal_hold": row.legal_hold, "requested_at": row.requested_at, "execute_after": row.execute_after, "completed_at": row.completed_at, "result": row.result} for row in rows]


@router.post("/privacy/lifecycle-requests/{request_id}/cancel")
async def cancel_lifecycle_request(
    request_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = (await db.execute(select(DataLifecycleRequest).where(DataLifecycleRequest.id == request_id, DataLifecycleRequest.user_id == current_user.id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Lifecycle request not found")
    if row.status not in {"requested", "grace_period"}:
        raise HTTPException(status_code=409, detail="This request can no longer be cancelled.")
    row.status = "cancelled"
    row.result = {**(row.result or {}), "cancelled_at": datetime.now(timezone.utc).isoformat()}
    await db.commit()
    return {"id": row.id, "status": row.status}


@router.get("/privacy/notices/current")
async def current_privacy_notice(audience: str = "student", jurisdiction: str = "IN", db: AsyncSession = Depends(get_db)) -> dict:
    row = (await db.execute(select(PrivacyNoticeVersion).where(PrivacyNoticeVersion.audience == audience, PrivacyNoticeVersion.jurisdiction == jurisdiction, PrivacyNoticeVersion.state == "published", PrivacyNoticeVersion.effective_from <= datetime.now(timezone.utc)).order_by(PrivacyNoticeVersion.version.desc()).limit(1))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="No published privacy notice for this audience")
    return {"id": row.id, "audience": row.audience, "jurisdiction": row.jurisdiction, "version": row.version, "body": row.body, "purposes": row.purposes, "effective_from": row.effective_from}


@router.post("/privacy/consents", status_code=201)
async def record_consent(body: ConsentCreate, current_user: CurrentUser, db: AsyncSession = Depends(get_db)) -> dict:
    notice = (await db.execute(select(PrivacyNoticeVersion).where(PrivacyNoticeVersion.id == body.notice_version_id, PrivacyNoticeVersion.state == "published"))).scalar_one_or_none()
    if notice is None or body.purpose_key not in set(notice.purposes or []):
        raise HTTPException(status_code=422, detail="Purpose is not present in the published notice")
    row = ConsentRecord(user_id=current_user.id, notice_version_id=notice.id, purpose_key=body.purpose_key, decision=body.decision, source=body.source, evidence=body.evidence)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"id": row.id, "purpose_key": row.purpose_key, "decision": row.decision, "recorded_at": row.recorded_at}


@router.post("/institutions/{institution_id}/privacy/notices", status_code=201)
async def create_privacy_notice(institution_id: UUID, body: PrivacyNoticeCreate, current_user: CurrentUser, current_session: CurrentApplicationSession, db: AsyncSession = Depends(get_db)) -> dict:
    await require_institution_capability(db, institution_id, current_user, "privacy.manage")
    await require_recent_reauthentication(current_session)
    version = int((await db.execute(select(PrivacyNoticeVersion.version).where(PrivacyNoticeVersion.audience == body.audience, PrivacyNoticeVersion.jurisdiction == body.jurisdiction).order_by(PrivacyNoticeVersion.version.desc()).limit(1))).scalar_one_or_none() or 0) + 1
    row = PrivacyNoticeVersion(audience=body.audience, jurisdiction=body.jurisdiction, version=version, body=body.body, purposes=body.purposes, state="draft", created_by=current_user.id)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"id": row.id, "version": row.version, "state": row.state}


@router.post("/institutions/{institution_id}/privacy/notices/{notice_id}/publish")
async def publish_privacy_notice(institution_id: UUID, notice_id: UUID, current_user: CurrentUser, current_session: CurrentApplicationSession, db: AsyncSession = Depends(get_db)) -> dict:
    await require_institution_capability(db, institution_id, current_user, "privacy.manage")
    await require_recent_reauthentication(current_session)
    row = (await db.execute(select(PrivacyNoticeVersion).where(PrivacyNoticeVersion.id == notice_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Privacy notice not found")
    if row.state not in {"draft", "under_review"}:
        raise HTTPException(status_code=409, detail="Only draft or reviewed notices can be published")
    row.state = "published"
    row.published_by = current_user.id
    row.published_at = datetime.now(timezone.utc)
    row.effective_from = row.effective_from or row.published_at
    await db.commit()
    return {"id": row.id, "version": row.version, "state": row.state, "effective_from": row.effective_from}


@router.post("/institutions/{institution_id}/privacy/data-inventory", status_code=201)
async def add_data_inventory(institution_id: UUID, body: DataInventoryCreate, current_user: CurrentUser, db: AsyncSession = Depends(get_db)) -> dict:
    await require_institution_capability(db, institution_id, current_user, "privacy.manage")
    purpose = (await db.execute(select(ProcessingPurpose).where(ProcessingPurpose.key == body.purpose_key, ProcessingPurpose.state == "active"))).scalar_one_or_none()
    if purpose is None:
        raise HTTPException(status_code=422, detail="Unknown processing purpose")
    row = DataInventoryRecord(institution_id=institution_id, data_category=body.data_category, purpose_key=body.purpose_key, subject_owner=body.subject_owner, storage_system=body.storage_system, retention_rule=body.retention_rule, shared_with=body.shared_with, deletion_path=body.deletion_path, durable_class=body.durable_class)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"id": row.id, "data_category": row.data_category, "purpose_key": row.purpose_key, "state": row.state}


@router.get("/institutions/{institution_id}/privacy/data-map")
async def institution_data_map(institution_id: UUID, current_user: CurrentUser, db: AsyncSession = Depends(get_db)) -> dict:
    await require_institution_capability(db, institution_id, current_user, "privacy.read")
    inventory = list((await db.execute(select(DataInventoryRecord).where(DataInventoryRecord.institution_id == institution_id, DataInventoryRecord.state == "active").order_by(DataInventoryRecord.data_category))).scalars())
    subprocessors = list((await db.execute(select(SubprocessorRecord).where(SubprocessorRecord.state == "active").order_by(SubprocessorRecord.name))).scalars())
    return {"institution_id": institution_id, "inventory": [{"data_category": row.data_category, "purpose": row.purpose_key, "owner": row.subject_owner, "storage": row.storage_system, "retention": row.retention_rule, "shared_with": row.shared_with, "deletion_path": row.deletion_path, "durable_class": row.durable_class} for row in inventory], "subprocessors": [{"name": row.name, "service": row.service, "purpose_keys": row.purpose_keys, "data_categories": row.data_categories, "processing_locations": row.processing_locations, "effective_from": row.effective_from} for row in subprocessors], "legal_review_required": True}
