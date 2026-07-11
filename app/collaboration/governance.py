"""Versioned institutional policies, profiles and official template governance."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collaboration.approval_invalidation import invalidate_profile_approvals
from app.models.event import Event
from app.models.institutional_governance import (
    InstitutionalPolicyVersion,
    InstitutionalProfileVersion,
    OfficialTemplateVersion,
    RetentionPolicy,
)
from app.models.project import Project


class GovernanceError(RuntimeError):
    pass


DEFAULT_POLICY = {
    "ai_policy": {
        "coaching": True,
        "rewrite_proposals": True,
        "source_discovery": True,
        "full_section_generation": False,
        "disclosure_required": True,
    },
    "workflow": {
        "supervisor_approval_required": True,
        "format_review_required": True,
        "institutional_approval_required": True,
        "student_final_attestation_required": True,
    },
    "privacy": {
        "admin_content_access_default": False,
        "supervisor_private_ai_history_default": False,
        "email_content_previews": False,
    },
    "permissions": {
        "operator_prose_edit": False,
        "student_draft_download": True,
        "external_review_allowed": True,
    },
}


def validate_policy(policy: dict[str, Any]) -> dict[str, Any]:
    merged = {
        section: {**values, **dict(policy.get(section) or {})}
        for section, values in DEFAULT_POLICY.items()
    }
    if merged["privacy"].get("admin_content_access_default") is True:
        raise GovernanceError(
            "Institution administrators cannot receive default manuscript-content access; use explicit project membership."
        )
    if merged["ai_policy"].get("full_section_generation") is True:
        raise GovernanceError("Autonomous full-section generation is not an allowed institutional policy.")
    return merged


async def next_policy_version(
    db: AsyncSession, institution_id: UUID, department_id: UUID | None
) -> int:
    clauses = [InstitutionalPolicyVersion.institution_id == institution_id]
    clauses.append(
        InstitutionalPolicyVersion.department_id.is_(None)
        if department_id is None
        else InstitutionalPolicyVersion.department_id == department_id
    )
    current = int(
        (await db.execute(select(func.coalesce(func.max(InstitutionalPolicyVersion.version), 0)).where(*clauses))).scalar_one()
    )
    return current + 1


async def create_policy_draft(
    db: AsyncSession,
    institution_id: UUID,
    actor_id: UUID,
    *,
    department_id: UUID | None,
    label: str,
    policy: dict,
) -> InstitutionalPolicyVersion:
    row = InstitutionalPolicyVersion(
        institution_id=institution_id,
        department_id=department_id,
        version=await next_policy_version(db, institution_id, department_id),
        label=label,
        state="draft",
        policy=validate_policy(policy),
        created_by=actor_id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def publish_policy(
    db: AsyncSession, row: InstitutionalPolicyVersion, actor_id: UUID
) -> InstitutionalPolicyVersion:
    if row.state not in {"draft", "staging"}:
        raise GovernanceError("Only draft or staging policies can be published.")
    row.policy = validate_policy(row.policy or {})
    row.state = "published"
    row.published_by = actor_id
    row.published_at = datetime.now(timezone.utc)
    row.effective_from = row.effective_from or row.published_at
    db.add(
        Event(
            project_id=None,
            user_id=actor_id,
            kind="institutional_policy_published",
            data={
                "institution_id": str(row.institution_id),
                "department_id": str(row.department_id) if row.department_id else None,
                "policy_version_id": str(row.id),
                "version": row.version,
            },
        )
    )
    await db.commit()
    await db.refresh(row)
    return row


def profile_impact(old: dict | None, new: dict | None) -> dict:
    old = old or {}
    new = new or {}
    keys = sorted(set(old) | set(new))
    changes = []
    for key in keys:
        if old.get(key) != new.get(key):
            changes.append({"path": key, "before": old.get(key), "after": new.get(key)})
    page_affecting = {
        "margin_left", "margin_right", "margin_top", "margin_bottom", "font_size",
        "line_spacing", "paragraph_spacing", "page_size",
    }
    estimated_page_delta = sum(1 for item in changes if item["path"] in page_affecting)
    return {
        "changes": changes,
        "changed_fields": len(changes),
        "estimated_page_delta_direction": "increase_possible" if estimated_page_delta else "unknown",
        "requires_preview_regeneration": bool(changes),
        "requires_formatting_reapproval": bool(changes),
    }


async def next_profile_version(
    db: AsyncSession,
    institution_id: UUID,
    department_id: UUID | None,
    programme: str,
    academic_year: str,
) -> int:
    query = select(func.coalesce(func.max(InstitutionalProfileVersion.version), 0)).where(
        InstitutionalProfileVersion.institution_id == institution_id,
        InstitutionalProfileVersion.programme == programme,
        InstitutionalProfileVersion.academic_year == academic_year,
    )
    query = query.where(
        InstitutionalProfileVersion.department_id.is_(None)
        if department_id is None
        else InstitutionalProfileVersion.department_id == department_id
    )
    return int((await db.execute(query)).scalar_one()) + 1


async def create_profile_draft(
    db: AsyncSession,
    institution_id: UUID,
    actor_id: UUID,
    *,
    department_id: UUID | None,
    programme: str,
    academic_year: str,
    label: str,
    base_profile: str,
    profile_data: dict,
    required_front_matter: list,
    locked_template_ids: list,
) -> InstitutionalProfileVersion:
    previous = (
        await db.execute(
            select(InstitutionalProfileVersion)
            .where(
                InstitutionalProfileVersion.institution_id == institution_id,
                InstitutionalProfileVersion.department_id == department_id,
                InstitutionalProfileVersion.programme == programme,
                InstitutionalProfileVersion.academic_year == academic_year,
                InstitutionalProfileVersion.state == "published",
            )
            .order_by(InstitutionalProfileVersion.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    row = InstitutionalProfileVersion(
        institution_id=institution_id,
        department_id=department_id,
        programme=programme,
        academic_year=academic_year,
        version=await next_profile_version(db, institution_id, department_id, programme, academic_year),
        label=label,
        state="draft",
        base_profile=base_profile,
        profile_data=profile_data,
        required_front_matter=required_front_matter,
        locked_template_ids=locked_template_ids,
        impact_summary=profile_impact(previous.profile_data if previous else {}, profile_data),
        created_by=actor_id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def publish_profile(
    db: AsyncSession, row: InstitutionalProfileVersion, actor_id: UUID
) -> InstitutionalProfileVersion:
    if row.state not in {"draft", "staging"}:
        raise GovernanceError("Only draft or staging profile versions can be published.")
    row.state = "published"
    row.published_by = actor_id
    row.published_at = datetime.now(timezone.utc)
    row.effective_from = row.effective_from or row.published_at
    await db.commit()
    await db.refresh(row)
    return row


async def pin_project_governance(
    db: AsyncSession,
    project: Project,
    actor_id: UUID,
    *,
    profile: InstitutionalProfileVersion | None = None,
    policy: InstitutionalPolicyVersion | None = None,
    mandatory: bool = False,
) -> None:
    if profile is not None:
        if profile.state != "published":
            raise GovernanceError("Projects may only pin published profile versions.")
        if profile.institution_id != project.institution_id:
            raise GovernanceError("Profile belongs to another institution.")
        project.institutional_profile_version_id = profile.id
        project.format_profile = profile.base_profile
        await invalidate_profile_approvals(
            db,
            project,
            actor_id,
            "Institutional format profile version changed; formatting, institutional and submission approvals are stale.",
        )
    if policy is not None:
        if policy.state != "published":
            raise GovernanceError("Projects may only pin published policy versions.")
        if policy.institution_id != project.institution_id:
            raise GovernanceError("Policy belongs to another institution.")
        project.institutional_policy_version_id = policy.id
        project.collaboration_policy = validate_policy(policy.policy or {})
    db.add(
        Event(
            project_id=project.id,
            user_id=actor_id,
            kind="project_governance_version_pinned",
            data={
                "profile_version_id": str(profile.id) if profile else None,
                "policy_version_id": str(policy.id) if policy else None,
                "mandatory": mandatory,
            },
        )
    )
    await db.commit()


async def create_template_draft(
    db: AsyncSession,
    institution_id: UUID,
    actor_id: UUID,
    *,
    department_id: UUID | None,
    template_kind: str,
    body: str,
    structured: dict,
    academic_note: str | None,
) -> OfficialTemplateVersion:
    query = select(func.coalesce(func.max(OfficialTemplateVersion.version), 0)).where(
        OfficialTemplateVersion.institution_id == institution_id,
        OfficialTemplateVersion.template_kind == template_kind,
    )
    query = query.where(
        OfficialTemplateVersion.department_id.is_(None)
        if department_id is None
        else OfficialTemplateVersion.department_id == department_id
    )
    version = int((await db.execute(query)).scalar_one()) + 1
    row = OfficialTemplateVersion(
        institution_id=institution_id,
        department_id=department_id,
        template_kind=template_kind,
        version=version,
        body=body,
        structured=structured,
        academic_note=academic_note,
        created_by=actor_id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def publish_template(
    db: AsyncSession, row: OfficialTemplateVersion, actor_id: UUID
) -> OfficialTemplateVersion:
    if row.state not in {"draft", "under_review", "approved"}:
        raise GovernanceError("This official template version cannot be published.")
    now = datetime.now(timezone.utc)
    row.state = "published"
    row.approved_by = row.approved_by or actor_id
    row.approved_at = row.approved_at or now
    row.published_at = now
    await db.commit()
    await db.refresh(row)
    return row


async def create_retention_policy(
    db: AsyncSession, institution_id: UUID, actor_id: UUID, policy: dict
) -> RetentionPolicy:
    version = int(
        (
            await db.execute(
                select(func.coalesce(func.max(RetentionPolicy.version), 0)).where(
                    RetentionPolicy.institution_id == institution_id
                )
            )
        ).scalar_one()
    ) + 1
    row = RetentionPolicy(
        institution_id=institution_id,
        version=version,
        state="draft",
        policy=policy,
        created_by=actor_id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row
