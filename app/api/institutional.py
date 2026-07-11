"""Phase 4 institution control plane without default thesis-content access."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.collaboration.capabilities import require_institution_capability, require_project_capability
from app.collaboration.governance import (
    GovernanceError,
    create_policy_draft,
    create_profile_draft,
    create_retention_policy,
    create_template_draft,
    pin_project_governance,
    profile_impact,
    publish_policy,
    publish_profile,
    publish_template,
)
from app.db.deps import get_db
from app.models.event import Event
from app.models.export import Export
from app.models.institution import Institution
from app.models.institutional_governance import (
    InstitutionalPolicyVersion,
    InstitutionalProfileVersion,
    OfficialTemplateVersion,
    RetentionPolicy,
)
from app.models.project import Project
from app.models.tenancy import DataLifecycleRequest, ReviewAssignment, SupportAccessGrant
from app.models.user import User


router = APIRouter(tags=["institutional-governance"])


class PolicyDraft(BaseModel):
    department_id: UUID | None = None
    label: str = Field(..., min_length=2, max_length=100)
    policy: dict[str, Any]


class ProfileDraft(BaseModel):
    department_id: UUID | None = None
    programme: str = Field(..., min_length=2, max_length=160)
    academic_year: str = Field(..., min_length=4, max_length=40)
    label: str = Field(..., min_length=2, max_length=120)
    base_profile: str = Field("tn_university", max_length=100)
    profile_data: dict[str, Any]
    required_front_matter: list[str] = Field(default_factory=list, max_length=50)
    locked_template_ids: list[UUID] = Field(default_factory=list, max_length=50)


class TemplateDraft(BaseModel):
    department_id: UUID | None = None
    template_kind: Literal["certificate", "declaration", "ai_disclosure", "submission_statement", "degree_wording", "department_name"]
    body: str = Field(..., min_length=2, max_length=30000)
    structured: dict[str, Any] = Field(default_factory=dict)
    academic_note: str | None = Field(None, max_length=8000)


class PinGovernance(BaseModel):
    profile_version_id: UUID | None = None
    policy_version_id: UUID | None = None
    mandatory: bool = False


class RetentionDraft(BaseModel):
    policy: dict[str, Any]


class LifecycleCreate(BaseModel):
    request_type: Literal["project_export", "account_export", "project_delete", "account_delete", "institution_exit"]
    project_id: UUID | None = None
    reason: str | None = Field(None, max_length=8000)
    soft_delete_days: int = Field(30, ge=1, le=365)


class SupportGrantCreate(BaseModel):
    support_user_id: UUID
    capabilities: list[Literal["project.read_metadata", "project.read_content", "project.read_sources"]] = Field(default_factory=lambda: ["project.read_metadata"])
    consent_note: str = Field(..., min_length=5, max_length=8000)
    expires_in_hours: int = Field(4, ge=1, le=72)


class OnboardingPatch(BaseModel):
    state: Literal["setup_required", "departments_configured", "profiles_staged", "pilot", "production_ready"]


def _policy_dict(row: InstitutionalPolicyVersion) -> dict:
    return {"id": row.id, "institution_id": row.institution_id, "department_id": row.department_id, "version": row.version, "label": row.label, "state": row.state, "policy": row.policy, "effective_from": row.effective_from, "published_by": row.published_by, "published_at": row.published_at, "created_at": row.created_at}


def _profile_dict(row: InstitutionalProfileVersion) -> dict:
    return {"id": row.id, "institution_id": row.institution_id, "department_id": row.department_id, "programme": row.programme, "academic_year": row.academic_year, "version": row.version, "label": row.label, "state": row.state, "base_profile": row.base_profile, "profile_data": row.profile_data, "required_front_matter": row.required_front_matter, "locked_template_ids": row.locked_template_ids, "impact_summary": row.impact_summary, "effective_from": row.effective_from, "published_at": row.published_at, "created_at": row.created_at}


def _template_dict(row: OfficialTemplateVersion) -> dict:
    return {"id": row.id, "institution_id": row.institution_id, "department_id": row.department_id, "template_kind": row.template_kind, "version": row.version, "state": row.state, "body": row.body, "structured": row.structured, "academic_note": row.academic_note, "approved_by": row.approved_by, "approved_at": row.approved_at, "published_at": row.published_at, "created_at": row.created_at}


@router.post("/institutions/{institution_id}/policies", status_code=201)
async def add_policy(
    institution_id: UUID,
    body: PolicyDraft,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_institution_capability(db, institution_id, current_user, "policy.manage", department_id=body.department_id)
    try:
        row = await create_policy_draft(db, institution_id, current_user.id, department_id=body.department_id, label=body.label, policy=body.policy)
    except GovernanceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _policy_dict(row)


@router.get("/institutions/{institution_id}/policies")
async def list_policies(
    institution_id: UUID,
    current_user: CurrentUser,
    department_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    await require_institution_capability(db, institution_id, current_user, "policy.read", department_id=department_id)
    query = select(InstitutionalPolicyVersion).where(InstitutionalPolicyVersion.institution_id == institution_id)
    if department_id:
        query = query.where(InstitutionalPolicyVersion.department_id == department_id)
    rows = list((await db.execute(query.order_by(InstitutionalPolicyVersion.version.desc()))).scalars())
    return [_policy_dict(row) for row in rows]


@router.post("/institutions/{institution_id}/policies/{policy_id}/publish")
async def publish_policy_version(
    institution_id: UUID,
    policy_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_institution_capability(db, institution_id, current_user, "policy.manage")
    row = (await db.execute(select(InstitutionalPolicyVersion).where(InstitutionalPolicyVersion.id == policy_id, InstitutionalPolicyVersion.institution_id == institution_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Policy version not found")
    try:
        return _policy_dict(await publish_policy(db, row, current_user.id))
    except GovernanceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/institutions/{institution_id}/profiles", status_code=201)
async def add_profile(
    institution_id: UUID,
    body: ProfileDraft,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    capability = "profile.manage_institution" if body.department_id is None else "profile.manage_department"
    await require_institution_capability(db, institution_id, current_user, capability, department_id=body.department_id)
    row = await create_profile_draft(db, institution_id, current_user.id, department_id=body.department_id, programme=body.programme, academic_year=body.academic_year, label=body.label, base_profile=body.base_profile, profile_data=body.profile_data, required_front_matter=body.required_front_matter, locked_template_ids=[str(value) for value in body.locked_template_ids])
    return _profile_dict(row)


@router.get("/institutions/{institution_id}/profiles")
async def list_profiles(
    institution_id: UUID,
    current_user: CurrentUser,
    department_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    await require_institution_capability(db, institution_id, current_user, "project.read_metadata", department_id=department_id)
    query = select(InstitutionalProfileVersion).where(InstitutionalProfileVersion.institution_id == institution_id)
    if department_id:
        query = query.where(InstitutionalProfileVersion.department_id == department_id)
    rows = list((await db.execute(query.order_by(InstitutionalProfileVersion.created_at.desc()))).scalars())
    return [_profile_dict(row) for row in rows]


@router.post("/institutions/{institution_id}/profiles/{profile_id}/publish")
async def publish_profile_version(
    institution_id: UUID,
    profile_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = (await db.execute(select(InstitutionalProfileVersion).where(InstitutionalProfileVersion.id == profile_id, InstitutionalProfileVersion.institution_id == institution_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Profile version not found")
    capability = "profile.manage_institution" if row.department_id is None else "profile.manage_department"
    await require_institution_capability(db, institution_id, current_user, capability, department_id=row.department_id)
    try:
        return _profile_dict(await publish_profile(db, row, current_user.id))
    except GovernanceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/institutions/{institution_id}/profiles/{profile_id}/impact")
async def profile_upgrade_impact(
    institution_id: UUID,
    profile_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_institution_capability(db, institution_id, current_user, "project.read_metadata")
    row = (await db.execute(select(InstitutionalProfileVersion).where(InstitutionalProfileVersion.id == profile_id, InstitutionalProfileVersion.institution_id == institution_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Profile version not found")
    previous = (await db.execute(select(InstitutionalProfileVersion).where(InstitutionalProfileVersion.institution_id == institution_id, InstitutionalProfileVersion.department_id == row.department_id, InstitutionalProfileVersion.programme == row.programme, InstitutionalProfileVersion.academic_year == row.academic_year, InstitutionalProfileVersion.version < row.version).order_by(InstitutionalProfileVersion.version.desc()).limit(1))).scalar_one_or_none()
    affected = int((await db.execute(select(func.count(Project.id)).where(Project.institution_id == institution_id, Project.department_id == row.department_id, Project.institutional_profile_version_id == (previous.id if previous else None), Project.archived.is_(False)))).scalar_one())
    return {"profile": _profile_dict(row), "previous_profile_id": previous.id if previous else None, "impact": profile_impact(previous.profile_data if previous else {}, row.profile_data), "active_projects_affected": affected, "automatic_upgrade": False}


@router.post("/institutions/{institution_id}/templates", status_code=201)
async def add_template(
    institution_id: UUID,
    body: TemplateDraft,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_institution_capability(db, institution_id, current_user, "template.manage", department_id=body.department_id)
    row = await create_template_draft(db, institution_id, current_user.id, department_id=body.department_id, template_kind=body.template_kind, body=body.body, structured=body.structured, academic_note=body.academic_note)
    return _template_dict(row)


@router.post("/institutions/{institution_id}/templates/{template_id}/publish")
async def publish_template_version(
    institution_id: UUID,
    template_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_institution_capability(db, institution_id, current_user, "template.manage")
    row = (await db.execute(select(OfficialTemplateVersion).where(OfficialTemplateVersion.id == template_id, OfficialTemplateVersion.institution_id == institution_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Template version not found")
    try:
        return _template_dict(await publish_template(db, row, current_user.id))
    except GovernanceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/projects/{project_id}/institutional-governance/pin")
async def pin_project_versions(
    project_id: UUID,
    body: PinGovernance,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    access = await require_project_capability(db, project_id, current_user, "project.read_metadata")
    if "profile.manage_institution" not in access.capabilities and "profile.manage_department" not in access.capabilities and access.role != "student":
        raise HTTPException(status_code=404, detail="Project not found")
    profile = (await db.execute(select(InstitutionalProfileVersion).where(InstitutionalProfileVersion.id == body.profile_version_id))).scalar_one_or_none() if body.profile_version_id else None
    policy = (await db.execute(select(InstitutionalPolicyVersion).where(InstitutionalPolicyVersion.id == body.policy_version_id))).scalar_one_or_none() if body.policy_version_id else None
    try:
        await pin_project_governance(db, access.project, current_user.id, profile=profile, policy=policy, mandatory=body.mandatory)
    except GovernanceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"project_id": project_id, "profile_version_id": access.project.institutional_profile_version_id, "policy_version_id": access.project.institutional_policy_version_id}


@router.get("/institutions/{institution_id}/analytics")
async def institution_analytics(
    institution_id: UUID,
    current_user: CurrentUser,
    department_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    membership = await require_institution_capability(db, institution_id, current_user, "analytics.read_aggregate", department_id=department_id)
    scoped_department = department_id or (membership.department_id if membership.role == "department_admin" else None)
    query = select(Project.workflow_state, func.count(Project.id)).where(Project.institution_id == institution_id, Project.archived.is_(False))
    if scoped_department:
        query = query.where(Project.department_id == scoped_department)
    states = {state: count for state, count in (await db.execute(query.group_by(Project.workflow_state))).all()}
    assignment_query = select(func.count(ReviewAssignment.id)).join(Project, Project.id == ReviewAssignment.project_id).where(Project.institution_id == institution_id, ReviewAssignment.status == "open")
    if scoped_department:
        assignment_query = assignment_query.where(Project.department_id == scoped_department)
    overdue_query = assignment_query.where(ReviewAssignment.due_at < datetime.now(timezone.utc))
    export_query = select(Export.status, func.count(Export.id)).join(Project, Project.id == Export.project_id).where(Project.institution_id == institution_id)
    if scoped_department:
        export_query = export_query.where(Project.department_id == scoped_department)
    exports = {state: count for state, count in (await db.execute(export_query.group_by(Export.status))).all()}
    return {"institution_id": institution_id, "department_id": scoped_department, "projects_by_workflow_state": states, "open_assignments": int((await db.execute(assignment_query)).scalar_one()), "overdue_assignments": int((await db.execute(overdue_query)).scalar_one()), "exports_by_status": exports, "privacy": "Aggregate workflow operations only; no thesis prose, private AI chats, quality scores or student rankings."}


@router.post("/institutions/{institution_id}/retention-policies", status_code=201)
async def add_retention_policy(
    institution_id: UUID,
    body: RetentionDraft,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_institution_capability(db, institution_id, current_user, "retention.manage")
    row = await create_retention_policy(db, institution_id, current_user.id, body.policy)
    return {"id": row.id, "version": row.version, "state": row.state, "policy": row.policy}


@router.post("/institutions/{institution_id}/lifecycle-requests", status_code=201)
async def create_lifecycle_request(
    institution_id: UUID,
    body: LifecycleCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    if body.project_id:
        access = await require_project_capability(db, body.project_id, current_user, "project.read_metadata")
        if access.project.institution_id != institution_id:
            raise HTTPException(status_code=404, detail="Institution workspace not found")
    elif current_user.institution_id != institution_id:
        raise HTTPException(status_code=404, detail="Institution workspace not found")
    row = DataLifecycleRequest(institution_id=institution_id, user_id=current_user.id, project_id=body.project_id, request_type=body.request_type, reason=body.reason, execute_after=datetime.now(timezone.utc) + timedelta(days=body.soft_delete_days))
    db.add(row); await db.commit(); await db.refresh(row)
    return {"id": row.id, "request_type": row.request_type, "status": row.status, "requested_at": row.requested_at, "execute_after": row.execute_after, "backup_notice": "Deletion from active systems may precede expiry from encrypted backups according to the published retention policy."}


@router.post("/projects/{project_id}/support-access", status_code=201)
async def grant_support_access(
    project_id: UUID,
    body: SupportGrantCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    access = await require_project_capability(db, project_id, current_user, "project.read_metadata")
    if access.role != "student" and "support.manage" not in access.capabilities:
        raise HTTPException(status_code=404, detail="Project not found")
    support_user = (await db.execute(select(User).where(User.id == body.support_user_id))).scalar_one_or_none()
    if support_user is None:
        raise HTTPException(status_code=404, detail="Support user not found")
    row = SupportAccessGrant(project_id=project_id, support_user_id=body.support_user_id, granted_by=current_user.id, capabilities=body.capabilities, consent_note=body.consent_note, expires_at=datetime.now(timezone.utc) + timedelta(hours=body.expires_in_hours))
    db.add(row); db.add(Event(project_id=project_id, user_id=current_user.id, kind="support_access_granted", data={"grant_id": str(row.id), "support_user_id": str(body.support_user_id), "capabilities": body.capabilities, "expires_at": row.expires_at.isoformat()}))
    await db.commit(); await db.refresh(row)
    return {"id": row.id, "status": row.status, "capabilities": row.capabilities, "expires_at": row.expires_at, "visibility_banner_required": True}


@router.patch("/institutions/{institution_id}/onboarding")
async def update_onboarding(
    institution_id: UUID,
    body: OnboardingPatch,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_institution_capability(db, institution_id, current_user, "institution.onboard")
    row = (await db.execute(select(Institution).where(Institution.id == institution_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Institution workspace not found")
    row.onboarding_state = body.state
    await db.commit()
    return {"institution_id": institution_id, "onboarding_state": row.onboarding_state}
