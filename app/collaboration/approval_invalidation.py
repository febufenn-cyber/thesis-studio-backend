"""Invalidate only approval dimensions affected by a canonical command."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.editor.commands import CommandResult
from app.models.event import Event
from app.models.project import Project
from app.models.review_collaboration import ApprovalRecord


async def invalidate_approvals_for_command(
    db: AsyncSession,
    project: Project,
    user_id: UUID,
    command_type: str,
    result: CommandResult,
) -> list[ApprovalRecord]:
    dimensions: set[str] = {"submission"}
    changed_chapters = {str(value) for value in result.changed_chapter_ids}
    citation_blocks = set(result.invalidations.get("citation_block_ids", []))
    quote_ids = set(result.invalidations.get("quote_ids", []))

    if result.changed_block_ids or changed_chapters:
        dimensions.add("content")
    if citation_blocks or quote_ids:
        dimensions.add("citation")
    if command_type in {
        "update_metadata", "update_front_matter_body", "set_front_matter_status",
        "reorder_front_matter", "reorder_chapters", "change_block_type", "move_block",
        "insert_block", "delete_block",
    }:
        dimensions.update({"formatting", "institutional"})

    rows = list(
        (
            await db.execute(
                select(ApprovalRecord).where(
                    ApprovalRecord.project_id == project.id,
                    ApprovalRecord.status == "active",
                    ApprovalRecord.dimension.in_(dimensions),
                )
            )
        ).scalars()
    )
    now = datetime.now(timezone.utc)
    for row in rows:
        if row.scope_type == "chapter" and row.scope_id and changed_chapters:
            if str(row.scope_id) not in changed_chapters and row.dimension == "content":
                continue
        row.status = "stale"
        row.invalidated_at = now
        row.invalidated_reason = (
            f"{row.dimension} approval became outdated after {command_type} at document "
            f"version {project.document_version + 1}."
        )

    if rows:
        event = Event(
            project_id=project.id,
            user_id=user_id,
            kind="approvals_invalidated",
            data={
                "dimensions": sorted({row.dimension for row in rows}),
                "approval_ids": [str(row.id) for row in rows],
                "command_type": command_type,
                "changed_chapter_ids": sorted(changed_chapters),
            },
        )
        db.add(event)
        await db.flush()
        for row in rows:
            row.invalidated_by_event_id = event.id
    return rows


async def invalidate_profile_approvals(
    db: AsyncSession, project: Project, user_id: UUID, reason: str
) -> list[ApprovalRecord]:
    rows = list(
        (
            await db.execute(
                select(ApprovalRecord).where(
                    ApprovalRecord.project_id == project.id,
                    ApprovalRecord.status == "active",
                    ApprovalRecord.dimension.in_(("formatting", "institutional", "submission")),
                )
            )
        ).scalars()
    )
    now = datetime.now(timezone.utc)
    for row in rows:
        row.status = "stale"
        row.invalidated_at = now
        row.invalidated_reason = reason
    return rows
