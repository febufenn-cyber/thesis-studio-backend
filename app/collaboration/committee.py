"""Committee roles and permissions (docs/LLD.md 3.6).

A closed, deny-by-default permission table. An unknown role grants nothing.
Membership is resolved from ``committee_memberships``; the project owner is the
candidate and is handled by the caller (owner-gated endpoints).
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.supervision import CommitteeMembership


class CommitteeRole(StrEnum):
    STUDENT = "student"
    ADVISOR = "advisor"
    CO_ADVISOR = "co_advisor"
    COMMITTEE_MEMBER = "committee_member"
    INTERNAL_EXAMINER = "internal_examiner"
    EXTERNAL_EXAMINER = "external_examiner"
    CHAIR = "chair"


class SupervisionPermission(StrEnum):
    VIEW_CONTENT = "supervision.view_content"
    COMMENT = "supervision.comment"
    RESOLVE_ANY = "supervision.resolve_any"
    APPROVE_CHAPTER = "supervision.approve_chapter"
    APPROVE_ACADEMIC = "supervision.approve_academic"
    ASSIGN_COMMITTEE = "supervision.assign_committee"


_P = SupervisionPermission
COMMITTEE_PERMISSIONS: dict[str, frozenset[SupervisionPermission]] = {
    CommitteeRole.ADVISOR: frozenset(
        {_P.VIEW_CONTENT, _P.COMMENT, _P.RESOLVE_ANY, _P.APPROVE_CHAPTER, _P.APPROVE_ACADEMIC, _P.ASSIGN_COMMITTEE}
    ),
    CommitteeRole.CO_ADVISOR: frozenset(
        {_P.VIEW_CONTENT, _P.COMMENT, _P.RESOLVE_ANY, _P.APPROVE_CHAPTER}
    ),
    CommitteeRole.COMMITTEE_MEMBER: frozenset({_P.VIEW_CONTENT, _P.COMMENT, _P.APPROVE_CHAPTER}),
    CommitteeRole.INTERNAL_EXAMINER: frozenset({_P.VIEW_CONTENT, _P.COMMENT, _P.APPROVE_CHAPTER}),
    CommitteeRole.EXTERNAL_EXAMINER: frozenset({_P.VIEW_CONTENT}),
    CommitteeRole.CHAIR: frozenset({_P.VIEW_CONTENT, _P.ASSIGN_COMMITTEE}),
}


def committee_permissions(role: str) -> frozenset[SupervisionPermission]:
    """Permissions for a role; empty for an unknown role (deny-by-default)."""
    return COMMITTEE_PERMISSIONS.get(role, frozenset())


async def get_active_membership(
    db: AsyncSession, project_id: UUID, user_id: UUID
) -> CommitteeMembership | None:
    return (
        await db.execute(
            select(CommitteeMembership).where(
                CommitteeMembership.project_id == project_id,
                CommitteeMembership.user_id == user_id,
                CommitteeMembership.status == "active",
            )
        )
    ).scalar_one_or_none()


async def member_has_permission(
    db: AsyncSession, project_id: UUID, user_id: UUID, permission: SupervisionPermission
) -> bool:
    """Whether an active committee member holds a permission (content-access aware)."""
    membership = await get_active_membership(db, project_id, user_id)
    if membership is None:
        return False
    perms = committee_permissions(membership.committee_role)
    if not membership.content_access and permission in {
        SupervisionPermission.VIEW_CONTENT,
        SupervisionPermission.COMMENT,
    }:
        return False
    return permission in perms
