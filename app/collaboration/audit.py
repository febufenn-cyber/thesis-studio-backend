"""Human-readable, privacy-aware audit timeline helpers."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event
from app.models.user import User


_LABELS = {
    "review_cycle_submitted": "submitted a thesis scope for supervisor review",
    "review_cycle_decided": "recorded a supervisor review decision",
    "collaboration_comment_added": "added a review comment",
    "human_suggestion_opened": "proposed a structured thesis change",
    "human_suggestion_decided": "recorded the student's decision on a suggestion",
    "approvals_invalidated": "made one or more approvals outdated through a later change",
    "workflow_state_changed": "changed the thesis workflow state",
    "supervisor_instruction_added": "recorded a supervisor instruction",
    "submission_package_sealed": "sealed an immutable submission package",
    "submission_package_withdrawn": "withdrew a sealed submission package without deleting history",
    "external_review_access_created": "created time-limited external review access",
    "project_governance_version_pinned": "changed the project's institutional policy/profile version",
    "project_membership_granted": "granted project access",
    "project_membership_revoked": "revoked project access",
    "project_handoff_recorded": "recorded a responsibility handoff",
    "workflow_attestation_recorded": "recorded an authenticated workflow attestation",
}


def humanize_event(row: Event, actor_name: str | None) -> dict:
    data = row.data or {}
    return {
        "id": row.id,
        "created_at": row.created_at,
        "actor_id": row.user_id,
        "actor_name": actor_name or "A workspace member",
        "kind": row.kind,
        "summary": f"{actor_name or 'A workspace member'} {_LABELS.get(row.kind, row.kind.replace('_', ' '))}.",
        "project_id": row.project_id,
        "document_version": data.get("document_version") or data.get("version_after") or data.get("current_document_version"),
        "review_cycle_id": data.get("review_cycle_id"),
        "target": {
            "comment_id": data.get("comment_id"),
            "suggestion_id": data.get("suggestion_id"),
            "approval_id": data.get("approval_id"),
            "submission_package_id": data.get("submission_package_id"),
            "target_type": data.get("target_type"),
            "target_id": data.get("target_id"),
        },
        "data": data,
    }


async def project_timeline(
    db: AsyncSession, project_id: UUID, *, limit: int = 200
) -> list[dict]:
    rows = list(
        (
            await db.execute(
                select(Event)
                .where(Event.project_id == project_id)
                .order_by(Event.created_at.desc())
                .limit(max(1, min(limit, 500)))
            )
        ).scalars()
    )
    user_ids = {row.user_id for row in rows}
    users = {
        row.id: row.full_name or row.email
        for row in (
            await db.execute(select(User).where(User.id.in_(user_ids)))
        ).scalars()
    } if user_ids else {}
    return [humanize_event(row, users.get(row.user_id)) for row in rows]
