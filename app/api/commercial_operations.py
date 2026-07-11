"""Release identity, component status, incidents, feature rollouts and recovery evidence."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentApplicationSession, CurrentUser
from app.collaboration.capabilities import require_institution_capability
from app.commercial.features import feature_enabled
from app.commercial.observability import release_identity
from app.commercial.recovery import (
    RecoveryError,
    complete_restore_drill,
    record_recovery_event,
    register_backup,
    start_restore_drill,
    verify_sealed_submission_restore,
)
from app.commercial.sessions import require_recent_reauthentication
from app.db.deps import get_db
from app.models.commercial import (
    BackupRecord,
    DeploymentRecord,
    FeatureFlag,
    RecoveryPolicy,
    ReleaseRecord,
    RestoreDrill,
    RolloutAssignment,
    ServiceComponent,
    ServiceIncident,
    SLODefinition,
)


router = APIRouter(tags=["commercial-operations"])


class IncidentCreate(BaseModel):
    severity: str = Field(..., pattern=r"^SEV-[123]$")
    title: str = Field(..., min_length=5, max_length=300)
    summary: str = Field(..., min_length=10, max_length=8000)
    component_keys: list[str] = Field(..., min_length=1, max_length=20)
    containment: dict = Field(default_factory=dict)


class IncidentUpdate(BaseModel):
    state: str = Field(..., pattern=r"^(investigating|identified|monitoring|resolved)$")
    summary: str | None = Field(None, max_length=8000)
    containment: dict | None = None


class FeatureFlagUpsert(BaseModel):
    description: str = Field(..., min_length=5, max_length=3000)
    default_enabled: bool = False
    rules: dict = Field(default_factory=dict)


class RolloutCreate(BaseModel):
    enabled: bool
    user_id: UUID | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    reason: str = Field(..., min_length=5, max_length=2000)


class RecoveryPolicyCreate(BaseModel):
    artifact_class: str = Field(..., min_length=2, max_length=60)
    rpo_minutes: int = Field(..., ge=0, le=525600)
    rto_minutes: int = Field(..., ge=1, le=525600)
    durable: bool
    backup_method: str = Field(..., min_length=3, max_length=120)
    restore_runbook: str = Field(..., min_length=20, max_length=20000)


class BackupCreate(BaseModel):
    policy_id: UUID
    scope: str = Field(..., min_length=2, max_length=80)
    storage_reference: str = Field(..., min_length=3, max_length=500)
    checksum: str = Field(..., min_length=32, max_length=128)
    encrypted: bool = True
    metadata: dict = Field(default_factory=dict)


class RestoreStart(BaseModel):
    backup_id: UUID
    target_environment: str = Field("restore-drill", min_length=2, max_length=40)
    expected_checksum: str | None = Field(None, min_length=32, max_length=128)


class RestoreComplete(BaseModel):
    restored_checksum: str = Field(..., min_length=32, max_length=128)
    evidence: dict = Field(default_factory=dict)


class SealedRestoreVerify(BaseModel):
    restored_package_manifest: dict


@router.get("/meta/release")
async def release_meta() -> dict:
    return release_identity()


@router.get("/status")
async def public_status(db: AsyncSession = Depends(get_db)) -> dict:
    components = list(
        (
            await db.execute(
                select(ServiceComponent)
                .where(ServiceComponent.public_status.is_(True))
                .order_by(ServiceComponent.key)
            )
        ).scalars()
    )
    incidents = list(
        (
            await db.execute(
                select(ServiceIncident)
                .where(ServiceIncident.state != "resolved", ServiceIncident.institution_id.is_(None))
                .order_by(ServiceIncident.started_at.desc())
                .limit(20)
            )
        ).scalars()
    )
    return {
        "generated_at": datetime.now(timezone.utc),
        "overall": "degraded" if any(row.state != "operational" for row in components) else "operational",
        "components": [{"key": row.key, "name": row.name, "state": row.state, "checked_at": row.checked_at} for row in components],
        "active_incidents": [{"id": row.id, "severity": row.severity, "title": row.title, "summary": row.summary, "state": row.state, "component_keys": row.component_keys, "started_at": row.started_at} for row in incidents],
        "ai_reported_separately": True,
    }


@router.get("/institutions/{institution_id}/operations")
async def institution_operations(
    institution_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_institution_capability(db, institution_id, current_user, "reliability.read")
    incidents = list((await db.execute(select(ServiceIncident).where(ServiceIncident.institution_id == institution_id).order_by(ServiceIncident.started_at.desc()).limit(100))).scalars())
    deployments = list((await db.execute(select(DeploymentRecord).order_by(DeploymentRecord.created_at.desc()).limit(25))).scalars())
    drills = list((await db.execute(select(RestoreDrill).order_by(RestoreDrill.created_at.desc()).limit(25))).scalars())
    return {
        "release": release_identity(),
        "incidents": [{"id": row.id, "severity": row.severity, "title": row.title, "state": row.state, "started_at": row.started_at, "resolved_at": row.resolved_at} for row in incidents],
        "recent_deployments": [{"id": row.id, "environment": row.environment, "strategy": row.strategy, "state": row.state, "started_at": row.started_at, "completed_at": row.completed_at} for row in deployments],
        "recent_restore_drills": [{"id": row.id, "state": row.state, "target_environment": row.target_environment, "duration_seconds": row.duration_seconds, "completed_at": row.completed_at} for row in drills],
    }


@router.post("/institutions/{institution_id}/incidents", status_code=201)
async def create_incident(
    institution_id: UUID,
    body: IncidentCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_institution_capability(db, institution_id, current_user, "incident.manage")
    known = set((await db.execute(select(ServiceComponent.key))).scalars())
    unknown = sorted(set(body.component_keys) - known)
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown components: {', '.join(unknown)}")
    row = ServiceIncident(
        severity=body.severity,
        title=body.title,
        summary=body.summary,
        component_keys=body.component_keys,
        institution_id=institution_id,
        incident_commander_id=current_user.id,
        communication_owner_id=current_user.id,
        technical_owner_id=current_user.id,
        containment=body.containment,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"id": row.id, "severity": row.severity, "state": row.state, "started_at": row.started_at}


@router.patch("/institutions/{institution_id}/incidents/{incident_id}")
async def update_incident(
    institution_id: UUID,
    incident_id: UUID,
    body: IncidentUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_institution_capability(db, institution_id, current_user, "incident.manage")
    row = (await db.execute(select(ServiceIncident).where(ServiceIncident.id == incident_id, ServiceIncident.institution_id == institution_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    row.state = body.state
    if body.summary is not None:
        row.summary = body.summary
    if body.containment is not None:
        row.containment = body.containment
    if body.state == "resolved":
        row.resolved_at = datetime.now(timezone.utc)
    await db.commit()
    return {"id": row.id, "state": row.state, "resolved_at": row.resolved_at}


@router.put("/institutions/{institution_id}/features/{key}")
async def upsert_feature_flag(
    institution_id: UUID,
    key: str,
    body: FeatureFlagUpsert,
    current_user: CurrentUser,
    current_session: CurrentApplicationSession,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_institution_capability(db, institution_id, current_user, "feature.manage")
    await require_recent_reauthentication(current_session)
    row = (await db.execute(select(FeatureFlag).where(FeatureFlag.key == key))).scalar_one_or_none()
    if row is None:
        row = FeatureFlag(key=key, description=body.description, default_enabled=body.default_enabled, rules=body.rules, created_by=current_user.id)
        db.add(row)
    else:
        row.description = body.description
        row.default_enabled = body.default_enabled
        row.rules = body.rules
    await db.commit()
    await db.refresh(row)
    return {"id": row.id, "key": row.key, "default_enabled": row.default_enabled, "state": row.state}


@router.post("/institutions/{institution_id}/features/{key}/rollouts", status_code=201)
async def create_rollout(
    institution_id: UUID,
    key: str,
    body: RolloutCreate,
    current_user: CurrentUser,
    current_session: CurrentApplicationSession,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_institution_capability(db, institution_id, current_user, "feature.manage")
    await require_recent_reauthentication(current_session)
    flag = (await db.execute(select(FeatureFlag).where(FeatureFlag.key == key))).scalar_one_or_none()
    if flag is None:
        raise HTTPException(status_code=404, detail="Feature flag not found")
    if body.ends_at and body.starts_at and body.ends_at <= body.starts_at:
        raise HTTPException(status_code=422, detail="Rollout end must be after start.")
    row = RolloutAssignment(feature_flag_id=flag.id, institution_id=institution_id, user_id=body.user_id, enabled=body.enabled, starts_at=body.starts_at, ends_at=body.ends_at, reason=body.reason, created_by=current_user.id)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"id": row.id, "enabled": row.enabled, "institution_id": row.institution_id, "user_id": row.user_id, "starts_at": row.starts_at, "ends_at": row.ends_at}


@router.get("/institutions/{institution_id}/features/{key}/effective")
async def effective_feature(
    institution_id: UUID,
    key: str,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_institution_capability(db, institution_id, current_user, "reliability.read")
    return {"key": key, "enabled": await feature_enabled(db, key, institution_id=institution_id, user_id=current_user.id)}


@router.post("/institutions/{institution_id}/recovery-policies", status_code=201)
async def create_recovery_policy(
    institution_id: UUID,
    body: RecoveryPolicyCreate,
    current_user: CurrentUser,
    current_session: CurrentApplicationSession,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_institution_capability(db, institution_id, current_user, "reliability.manage")
    await require_recent_reauthentication(current_session)
    existing = (await db.execute(select(RecoveryPolicy).where(RecoveryPolicy.institution_id == institution_id, RecoveryPolicy.artifact_class == body.artifact_class))).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Recovery policy already exists for this artifact class.")
    row = RecoveryPolicy(institution_id=institution_id, artifact_class=body.artifact_class, rpo_minutes=body.rpo_minutes, rto_minutes=body.rto_minutes, durable=body.durable, backup_method=body.backup_method, restore_runbook=body.restore_runbook, created_by=current_user.id)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"id": row.id, "artifact_class": row.artifact_class, "rpo_minutes": row.rpo_minutes, "rto_minutes": row.rto_minutes, "durable": row.durable}


@router.post("/institutions/{institution_id}/backups", status_code=201)
async def create_backup_record(
    institution_id: UUID,
    body: BackupCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_institution_capability(db, institution_id, current_user, "reliability.manage")
    policy = (await db.execute(select(RecoveryPolicy).where(RecoveryPolicy.id == body.policy_id, RecoveryPolicy.institution_id == institution_id))).scalar_one_or_none()
    if policy is None:
        raise HTTPException(status_code=404, detail="Recovery policy not found")
    try:
        row = await register_backup(db, policy, scope=body.scope, storage_reference=body.storage_reference, checksum=body.checksum, encrypted=body.encrypted, metadata=body.metadata)
    except RecoveryError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await db.commit()
    await db.refresh(row)
    return {"id": row.id, "state": row.state, "checksum": row.checksum, "encrypted": row.encrypted, "completed_at": row.completed_at}


@router.post("/institutions/{institution_id}/restore-drills", status_code=201)
async def begin_restore_drill(
    institution_id: UUID,
    body: RestoreStart,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_institution_capability(db, institution_id, current_user, "reliability.manage")
    backup = (await db.execute(select(BackupRecord).join(RecoveryPolicy, RecoveryPolicy.id == BackupRecord.policy_id).where(BackupRecord.id == body.backup_id, RecoveryPolicy.institution_id == institution_id))).scalar_one_or_none()
    if backup is None:
        raise HTTPException(status_code=404, detail="Backup not found")
    try:
        row = await start_restore_drill(db, backup, target_environment=body.target_environment, actor_id=current_user.id, expected_checksum=body.expected_checksum)
    except RecoveryError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await db.commit()
    await db.refresh(row)
    return {"id": row.id, "state": row.state, "expected_checksum": row.expected_checksum, "started_at": row.started_at}


@router.post("/institutions/{institution_id}/restore-drills/{drill_id}/complete")
async def finish_restore_drill(
    institution_id: UUID,
    drill_id: UUID,
    body: RestoreComplete,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_institution_capability(db, institution_id, current_user, "reliability.manage")
    drill = (await db.execute(select(RestoreDrill).join(BackupRecord, BackupRecord.id == RestoreDrill.backup_id).join(RecoveryPolicy, RecoveryPolicy.id == BackupRecord.policy_id).where(RestoreDrill.id == drill_id, RecoveryPolicy.institution_id == institution_id))).scalar_one_or_none()
    if drill is None:
        raise HTTPException(status_code=404, detail="Restore drill not found")
    try:
        await complete_restore_drill(db, drill, restored_checksum=body.restored_checksum, evidence=body.evidence)
    except RecoveryError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await record_recovery_event(db, actor_id=current_user.id, drill=drill, institution_id=institution_id)
    await db.commit()
    return {"id": drill.id, "state": drill.state, "checksum_match": drill.expected_checksum == drill.restored_checksum, "duration_seconds": drill.duration_seconds}


@router.post("/institutions/{institution_id}/sealed-submissions/{package_id}/verify-restore")
async def verify_sealed_restore(
    institution_id: UUID,
    package_id: UUID,
    body: SealedRestoreVerify,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_institution_capability(db, institution_id, current_user, "reliability.manage")
    try:
        return await verify_sealed_submission_restore(db, package_id, restored_package_manifest=body.restored_package_manifest)
    except RecoveryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
