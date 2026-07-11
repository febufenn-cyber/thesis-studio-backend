"""Institutional staging, publication and onboarding readiness endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.collaboration.capabilities import require_institution_capability
from app.collaboration.governance import GovernanceError, validate_policy
from app.db.deps import get_db
from app.models.institution import Institution
from app.models.institutional_governance import (
    InstitutionalPolicyVersion,
    InstitutionalProfileVersion,
    OfficialTemplateVersion,
    RetentionPolicy,
)
from app.models.project import Project
from app.models.tenancy import Department, OrganizationMembership


router = APIRouter(tags=["institutional-governance"])


class StateTransition(BaseModel):
    target: Literal["staging", "under_review", "approved", "published", "deprecated"]


async def _policy_row(
    db: AsyncSession, institution_id: UUID, row_id: UUID
) -> InstitutionalPolicyVersion:
    row = (
        await db.execute(
            select(InstitutionalPolicyVersion).where(
                InstitutionalPolicyVersion.id == row_id,
                InstitutionalPolicyVersion.institution_id == institution_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Policy version not found")
    return row


async def _profile_row(
    db: AsyncSession, institution_id: UUID, row_id: UUID
) -> InstitutionalProfileVersion:
    row = (
        await db.execute(
            select(InstitutionalProfileVersion).where(
                InstitutionalProfileVersion.id == row_id,
                InstitutionalProfileVersion.institution_id == institution_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Profile version not found")
    return row


async def _template_row(
    db: AsyncSession, institution_id: UUID, row_id: UUID
) -> OfficialTemplateVersion:
    row = (
        await db.execute(
            select(OfficialTemplateVersion).where(
                OfficialTemplateVersion.id == row_id,
                OfficialTemplateVersion.institution_id == institution_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Template version not found")
    return row


@router.post("/institutions/{institution_id}/policies/{policy_id}/state")
async def transition_policy_state(
    institution_id: UUID,
    policy_id: UUID,
    body: StateTransition,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_institution_capability(db, institution_id, current_user, "policy.manage")
    row = await _policy_row(db, institution_id, policy_id)
    allowed = {
        "draft": {"staging"},
        "staging": {"published", "draft"},
        "published": {"deprecated"},
        "deprecated": set(),
    }
    if body.target not in allowed.get(row.state, set()):
        raise HTTPException(status_code=409, detail=f"Invalid policy transition: {row.state} → {body.target}")
    if body.target == "published":
        try:
            row.policy = validate_policy(row.policy or {})
        except GovernanceError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        row.published_by = current_user.id
        row.published_at = datetime.now(timezone.utc)
        row.effective_from = row.effective_from or row.published_at
    if body.target == "deprecated":
        row.deprecated_at = datetime.now(timezone.utc)
    row.state = body.target
    await db.commit()
    return {"id": row.id, "version": row.version, "state": row.state}


@router.post("/institutions/{institution_id}/profiles/{profile_id}/state")
async def transition_profile_state(
    institution_id: UUID,
    profile_id: UUID,
    body: StateTransition,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = await _profile_row(db, institution_id, profile_id)
    capability = "profile.manage_institution" if row.department_id is None else "profile.manage_department"
    await require_institution_capability(
        db, institution_id, current_user, capability, department_id=row.department_id
    )
    allowed = {
        "draft": {"staging"},
        "staging": {"published", "draft"},
        "published": {"deprecated"},
        "deprecated": set(),
    }
    if body.target not in allowed.get(row.state, set()):
        raise HTTPException(status_code=409, detail=f"Invalid profile transition: {row.state} → {body.target}")
    now = datetime.now(timezone.utc)
    if body.target == "published":
        row.published_by = current_user.id
        row.published_at = now
        row.effective_from = row.effective_from or now
    if body.target == "deprecated":
        row.deprecated_at = now
    row.state = body.target
    await db.commit()
    return {"id": row.id, "version": row.version, "state": row.state, "impact": row.impact_summary}


@router.get("/institutions/{institution_id}/templates")
async def list_template_versions(
    institution_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    await require_institution_capability(db, institution_id, current_user, "project.read_metadata")
    rows = list(
        (
            await db.execute(
                select(OfficialTemplateVersion)
                .where(OfficialTemplateVersion.institution_id == institution_id)
                .order_by(
                    OfficialTemplateVersion.template_kind,
                    OfficialTemplateVersion.version.desc(),
                )
            )
        ).scalars()
    )
    return [
        {
            "id": row.id,
            "department_id": row.department_id,
            "template_kind": row.template_kind,
            "version": row.version,
            "state": row.state,
            "body": row.body,
            "academic_note": row.academic_note,
            "approved_by": row.approved_by,
            "approved_at": row.approved_at,
            "published_at": row.published_at,
        }
        for row in rows
    ]


@router.post("/institutions/{institution_id}/templates/{template_id}/state")
async def transition_template_state(
    institution_id: UUID,
    template_id: UUID,
    body: StateTransition,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_institution_capability(db, institution_id, current_user, "template.manage")
    row = await _template_row(db, institution_id, template_id)
    allowed = {
        "draft": {"under_review"},
        "under_review": {"approved", "draft"},
        "approved": {"published", "under_review"},
        "published": {"deprecated"},
        "deprecated": set(),
    }
    if body.target not in allowed.get(row.state, set()):
        raise HTTPException(status_code=409, detail=f"Invalid template transition: {row.state} → {body.target}")
    now = datetime.now(timezone.utc)
    if body.target == "approved":
        row.approved_by = current_user.id
        row.approved_at = now
    if body.target == "published":
        if row.approved_by is None:
            raise HTTPException(status_code=409, detail="Official wording must be approved before publication")
        row.published_at = now
    if body.target == "deprecated":
        row.deprecated_at = now
    row.state = body.target
    await db.commit()
    return {"id": row.id, "template_kind": row.template_kind, "version": row.version, "state": row.state}


@router.get("/institutions/{institution_id}/retention-policies")
async def list_retention_policies(
    institution_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    await require_institution_capability(db, institution_id, current_user, "retention.manage")
    rows = list(
        (
            await db.execute(
                select(RetentionPolicy)
                .where(RetentionPolicy.institution_id == institution_id)
                .order_by(RetentionPolicy.version.desc())
            )
        ).scalars()
    )
    return [
        {
            "id": row.id,
            "version": row.version,
            "state": row.state,
            "policy": row.policy,
            "published_by": row.published_by,
            "published_at": row.published_at,
            "created_at": row.created_at,
        }
        for row in rows
    ]


@router.post("/institutions/{institution_id}/retention-policies/{policy_id}/publish")
async def publish_retention_policy(
    institution_id: UUID,
    policy_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_institution_capability(db, institution_id, current_user, "retention.manage")
    row = (
        await db.execute(
            select(RetentionPolicy).where(
                RetentionPolicy.id == policy_id,
                RetentionPolicy.institution_id == institution_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Retention policy not found")
    if row.state != "draft":
        raise HTTPException(status_code=409, detail="Only a draft retention policy can be published")
    row.state = "published"
    row.published_by = current_user.id
    row.published_at = datetime.now(timezone.utc)
    await db.commit()
    return {"id": row.id, "version": row.version, "state": row.state, "published_at": row.published_at}


@router.get("/institutions/{institution_id}/onboarding")
async def onboarding_readiness(
    institution_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_institution_capability(db, institution_id, current_user, "institution.onboard")
    institution = (
        await db.execute(select(Institution).where(Institution.id == institution_id))
    ).scalar_one_or_none()
    if institution is None:
        raise HTTPException(status_code=404, detail="Institution workspace not found")

    departments = int(
        (
            await db.execute(
                select(func.count(Department.id)).where(
                    Department.institution_id == institution_id,
                    Department.active.is_(True),
                )
            )
        ).scalar_one()
    )
    profiles = int(
        (
            await db.execute(
                select(func.count(InstitutionalProfileVersion.id)).where(
                    InstitutionalProfileVersion.institution_id == institution_id,
                    InstitutionalProfileVersion.state == "published",
                )
            )
        ).scalar_one()
    )
    policies = int(
        (
            await db.execute(
                select(func.count(InstitutionalPolicyVersion.id)).where(
                    InstitutionalPolicyVersion.institution_id == institution_id,
                    InstitutionalPolicyVersion.state == "published",
                )
            )
        ).scalar_one()
    )
    templates = int(
        (
            await db.execute(
                select(func.count(OfficialTemplateVersion.id)).where(
                    OfficialTemplateVersion.institution_id == institution_id,
                    OfficialTemplateVersion.state == "published",
                )
            )
        ).scalar_one()
    )
    verified_members = int(
        (
            await db.execute(
                select(func.count(OrganizationMembership.id)).where(
                    OrganizationMembership.institution_id == institution_id,
                    OrganizationMembership.status == "active",
                    OrganizationMembership.affiliation_status.in_(("domain_verified", "admin_verified")),
                )
            )
        ).scalar_one()
    )
    pilot_projects = int(
        (
            await db.execute(
                select(func.count(Project.id)).where(
                    Project.institution_id == institution_id,
                    Project.archived.is_(False),
                )
            )
        ).scalar_one()
    )
    checklist = {
        "departments": departments > 0,
        "published_profile": profiles > 0,
        "published_policy": policies > 0,
        "published_official_template": templates > 0,
        "verified_members": verified_members >= 2,
        "pilot_project": pilot_projects > 0,
    }
    return {
        "institution_id": institution_id,
        "onboarding_state": institution.onboarding_state,
        "production_ready": all(checklist.values()),
        "checklist": checklist,
        "counts": {
            "departments": departments,
            "published_profiles": profiles,
            "published_policies": policies,
            "published_templates": templates,
            "verified_members": verified_members,
            "pilot_projects": pilot_projects,
        },
        "sandbox_notice": (
            "Profiles, official wording and policy changes should be previewed in a pilot project "
            "before the workspace is marked production ready."
        ),
    }
