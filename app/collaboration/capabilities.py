"""Capability resolution for institutional, project and commercial operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.models.tenancy import OrganizationMembership, ProjectMembership, SupportAccessGrant
from app.models.user import User


STUDENT_CAPABILITIES = {
    "project.read_metadata", "project.read_content", "project.read_sources",
    "project.edit_content", "project.comment", "project.suggest", "project.submit_review",
    "project.respond_review", "project.accept_suggestion", "project.request_final_approval",
    "project.export_draft", "project.read_ai_history", "source.add", "quote.add",
    "ai.use", "membership.invite_reviewer", "submission.attest", "data.export_self",
    "data.request_deletion_self", "session.manage_self",
}

ROLE_CAPABILITIES: dict[str, set[str]] = {
    "student": set(STUDENT_CAPABILITIES),
    "supervisor": {
        "project.read_metadata", "project.read_content", "project.read_sources",
        "project.comment", "project.suggest", "project.approve_chapter",
        "project.approve_academic", "project.issue_instruction", "review.manage",
        "queue.review", "submission.attest", "session.manage_self",
    },
    "operator": {
        "project.read_metadata", "project.read_content", "project.read_sources",
        "project.comment", "project.edit_structure", "project.edit_metadata",
        "project.prepare_export", "project.approve_formatting", "queue.formatting",
        "submission.attest", "session.manage_self",
    },
    "department_admin": {
        "project.read_metadata", "membership.manage_department", "assignment.manage",
        "queue.department", "profile.manage_department", "policy.read",
        "project.transition_submission", "analytics.read_aggregate", "audit.read_metadata",
        "entitlement.read", "usage.read_aggregate", "reliability.read",
        "support.request", "session.manage_self",
    },
    "institution_admin": {
        "project.read_metadata", "membership.manage_institution", "assignment.manage",
        "queue.department", "profile.manage_institution", "template.manage",
        "policy.manage", "policy.read", "retention.manage", "audit.read_metadata",
        "analytics.read_aggregate", "support.manage", "institution.onboard",
        "project.transition_submission", "billing.manage", "billing.read",
        "entitlement.manage", "entitlement.read", "usage.read_aggregate",
        "budget.manage", "reliability.read", "reliability.manage", "incident.manage",
        "privacy.manage", "privacy.read", "security.read", "feature.manage",
        "session.revoke_member", "session.manage_self", "support.request",
    },
    "external_reviewer": {"sealed.read_metadata", "sealed.read_content"},
    "support": {
        "project.read_metadata", "support.console", "support.retry_job",
        "support.diagnostic", "session.revoke_support", "reliability.read",
    },
}

_VERIFIED_AFFILIATIONS = {"domain_verified", "admin_verified"}


@dataclass(frozen=True)
class ProjectAccess:
    project: Project
    capabilities: frozenset[str]
    role: str
    project_membership_id: UUID | None
    organization_membership_id: UUID | None
    content_access: bool
    source_access: bool
    ai_history_access: bool

    def allows(self, capability: str) -> bool:
        return capability in self.capabilities


def _apply_overrides(base: set[str], overrides: dict | None) -> set[str]:
    result = set(base)
    data = overrides or {}
    result.update(str(value) for value in data.get("add", []))
    result.difference_update(str(value) for value in data.get("remove", []))
    return result


def _active_until(expires_at: datetime | None, now: datetime) -> bool:
    return expires_at is None or expires_at > now


async def organization_membership(
    db: AsyncSession, institution_id: UUID, user_id: UUID
) -> OrganizationMembership | None:
    return (
        await db.execute(
            select(OrganizationMembership).where(
                OrganizationMembership.institution_id == institution_id,
                OrganizationMembership.user_id == user_id,
                OrganizationMembership.status == "active",
                OrganizationMembership.affiliation_status.in_(_VERIFIED_AFFILIATIONS),
            )
        )
    ).scalar_one_or_none()


async def resolve_project_access(
    db: AsyncSession,
    project_id: UUID,
    user: User,
    *,
    include_archived: bool = False,
) -> ProjectAccess | None:
    project = (
        await db.execute(
            select(Project).where(
                Project.id == project_id,
                or_(Project.archived.is_(False), include_archived),
            )
        )
    ).scalar_one_or_none()
    if project is None:
        return None
    if project.user_id == user.id:
        return ProjectAccess(
            project=project,
            capabilities=frozenset(STUDENT_CAPABILITIES),
            role="student",
            project_membership_id=None,
            organization_membership_id=None,
            content_access=True,
            source_access=True,
            ai_history_access=True,
        )

    institution_id = project.institution_id or user.institution_id
    org = await organization_membership(db, institution_id, user.id)
    now = datetime.now(timezone.utc)
    membership = (
        await db.execute(
            select(ProjectMembership).where(
                ProjectMembership.project_id == project.id,
                ProjectMembership.user_id == user.id,
                ProjectMembership.status == "active",
            )
        )
    ).scalar_one_or_none()
    if membership is not None and _active_until(membership.expires_at, now) and org is not None:
        capabilities = set(ROLE_CAPABILITIES.get(membership.role, set()))
        capabilities.update(str(value) for value in membership.capabilities or [])
        if not membership.content_access:
            capabilities.discard("project.read_content")
            capabilities.difference_update(
                {"project.edit_content", "project.edit_structure", "project.edit_metadata"}
            )
        if not membership.source_access:
            capabilities.difference_update({"project.read_sources", "source.verify"})
        if not membership.ai_history_access:
            capabilities.discard("project.read_ai_history")
        return ProjectAccess(
            project=project,
            capabilities=frozenset(capabilities),
            role=membership.role,
            project_membership_id=membership.id,
            organization_membership_id=org.id,
            content_access=membership.content_access,
            source_access=membership.source_access,
            ai_history_access=membership.ai_history_access,
        )

    if org is not None:
        department_match = org.department_id is None or org.department_id == project.department_id
        if department_match and org.role in {"department_admin", "institution_admin"}:
            capabilities = _apply_overrides(ROLE_CAPABILITIES[org.role], org.capability_overrides)
            return ProjectAccess(
                project=project,
                capabilities=frozenset(capabilities),
                role=org.role,
                project_membership_id=None,
                organization_membership_id=org.id,
                content_access=False,
                source_access=False,
                ai_history_access=False,
            )

    support = (
        await db.execute(
            select(SupportAccessGrant).where(
                SupportAccessGrant.project_id == project.id,
                SupportAccessGrant.support_user_id == user.id,
                SupportAccessGrant.status == "active",
                SupportAccessGrant.expires_at > now,
            )
        )
    ).scalar_one_or_none()
    if support is not None:
        caps = set(ROLE_CAPABILITIES["support"])
        caps.update(str(value) for value in support.capabilities or [])
        return ProjectAccess(
            project=project,
            capabilities=frozenset(caps),
            role="support",
            project_membership_id=None,
            organization_membership_id=None,
            content_access="project.read_content" in caps,
            source_access="project.read_sources" in caps,
            ai_history_access="project.read_ai_history" in caps,
        )
    return None


async def require_project_capability(
    db: AsyncSession,
    project_id: UUID,
    user: User,
    capability: str,
    *,
    include_archived: bool = False,
) -> ProjectAccess:
    access = await resolve_project_access(db, project_id, user, include_archived=include_archived)
    if access is None or not access.allows(capability):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return access


async def require_institution_capability(
    db: AsyncSession,
    institution_id: UUID,
    user: User,
    capability: str,
    *,
    department_id: UUID | None = None,
) -> OrganizationMembership:
    row = await organization_membership(db, institution_id, user.id)
    if row is None:
        raise HTTPException(status_code=404, detail="Institution workspace not found")
    if department_id is not None and row.role != "institution_admin" and row.department_id != department_id:
        raise HTTPException(status_code=404, detail="Institution workspace not found")
    capabilities = _apply_overrides(ROLE_CAPABILITIES.get(row.role, set()), row.capability_overrides)
    if capability not in capabilities:
        raise HTTPException(status_code=404, detail="Institution workspace not found")
    return row


async def accessible_project_ids(db: AsyncSession, user: User, capability: str) -> list[UUID]:
    """Return every project visible through ownership, assignment or admin scope.

    Organization administrators receive metadata scope only. This index never
    grants manuscript content; each project response is still resolved through
    ``resolve_project_access`` before it is returned.
    """

    result = set(
        (
            await db.execute(
                select(Project.id).where(
                    Project.user_id == user.id,
                    Project.archived.is_(False),
                )
            )
        ).scalars()
    )
    now = datetime.now(timezone.utc)
    memberships = list(
        (
            await db.execute(
                select(ProjectMembership).where(
                    ProjectMembership.user_id == user.id,
                    ProjectMembership.status == "active",
                )
            )
        ).scalars()
    )
    for membership in memberships:
        if not _active_until(membership.expires_at, now):
            continue
        caps = set(ROLE_CAPABILITIES.get(membership.role, set())) | set(
            membership.capabilities or []
        )
        if capability in caps:
            result.add(membership.project_id)

    org_rows = list(
        (
            await db.execute(
                select(OrganizationMembership).where(
                    OrganizationMembership.user_id == user.id,
                    OrganizationMembership.status == "active",
                    OrganizationMembership.affiliation_status.in_(_VERIFIED_AFFILIATIONS),
                    OrganizationMembership.role.in_(("department_admin", "institution_admin")),
                )
            )
        ).scalars()
    )
    for org in org_rows:
        caps = _apply_overrides(ROLE_CAPABILITIES.get(org.role, set()), org.capability_overrides)
        if capability not in caps:
            continue
        query = select(Project.id).where(
            Project.institution_id == org.institution_id,
            Project.archived.is_(False),
        )
        if org.role == "department_admin":
            if org.department_id is None:
                continue
            query = query.where(Project.department_id == org.department_id)
        result.update((await db.execute(query)).scalars())

    return sorted(result, key=str)
