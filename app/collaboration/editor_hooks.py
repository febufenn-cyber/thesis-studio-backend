"""Central Phase 4 approval invalidation for every Phase 2 canonical command.

The listener runs in the same database transaction as the append-only command, so
legacy/owner editor routes and collaboration-applied suggestions receive the same
approval semantics. It invalidates approval dimensions, not unrelated academic
judgments merely because presentation changed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import and_, event, or_, update

from app.models.document_command import DocumentCommand
from app.models.event import Event
from app.models.review_collaboration import ApprovalRecord


_CONTENT_COMMANDS = {
    "update_block", "update_block_text", "change_block_type", "delete_block",
    "duplicate_block", "move_block", "split_block", "merge_blocks", "insert_block",
    "add_marker", "restore_block_original", "restore_document", "restore_chapter",
    "update_chapter", "reorder_chapters", "update_front_matter_body",
    "restore_front_matter_entry",
}
_CITATION_COMMANDS = {
    "update_block", "update_block_text", "change_block_type", "delete_block",
    "move_block", "split_block", "merge_blocks", "restore_block_original",
    "restore_document", "update_works_cited",
}
_FORMAT_COMMANDS = {
    "update_metadata", "update_chapter", "set_chapter_status", "reorder_chapters",
    "reorder_front_matter", "update_front_matter_body", "set_front_matter_status",
    "change_block_type", "move_block", "insert_block", "delete_block",
    "restore_document", "restore_chapter", "restore_front_matter_entry",
}
_INSTITUTIONAL_COMMANDS = {
    "update_metadata", "reorder_front_matter", "update_front_matter_body",
    "set_front_matter_status", "restore_document", "restore_front_matter_entry",
}


def affected_dimensions(command_type: str) -> set[str]:
    dimensions = {"submission"}
    if command_type in _CONTENT_COMMANDS:
        dimensions.add("content")
    if command_type in _CITATION_COMMANDS:
        dimensions.add("citation")
    if command_type in _FORMAT_COMMANDS:
        dimensions.add("formatting")
    if command_type in _INSTITUTIONAL_COMMANDS:
        dimensions.add("institutional")
    return dimensions


def _chapter_ids(command: DocumentCommand) -> set[str]:
    payload = command.payload or {}
    result = set()
    for key in ("chapter_id", "to_chapter_id"):
        if payload.get(key):
            result.add(str(payload[key]))
    if command.target_type == "chapter" and command.target_id:
        result.add(str(command.target_id))
    return result


@event.listens_for(DocumentCommand, "after_insert")
def invalidate_approval_records(mapper, connection, command: DocumentCommand) -> None:  # noqa: ARG001
    dimensions = affected_dimensions(command.command_type)
    now = datetime.now(timezone.utc)
    event_id = uuid4()
    chapter_ids = _chapter_ids(command)

    base = and_(
        ApprovalRecord.__table__.c.project_id == command.project_id,
        ApprovalRecord.__table__.c.status == "active",
        ApprovalRecord.__table__.c.dimension.in_(sorted(dimensions)),
    )
    # When the command explicitly identifies chapters, preserve content approvals
    # for other chapters. Project-wide and non-content dimensions still invalidate.
    if chapter_ids:
        base = and_(
            base,
            or_(
                ApprovalRecord.__table__.c.dimension != "content",
                ApprovalRecord.__table__.c.scope_type != "chapter",
                ApprovalRecord.__table__.c.scope_id.in_(chapter_ids),
            ),
        )

    rows = connection.execute(
        ApprovalRecord.__table__.select()
        .with_only_columns(ApprovalRecord.__table__.c.id, ApprovalRecord.__table__.c.dimension)
        .where(base)
    ).all()
    if not rows:
        return

    connection.execute(
        Event.__table__.insert().values(
            id=event_id,
            project_id=command.project_id,
            user_id=command.user_id,
            kind="approvals_invalidated",
            data={
                "approval_ids": [str(row.id) for row in rows],
                "dimensions": sorted({row.dimension for row in rows}),
                "command_id": str(command.id),
                "command_type": command.command_type,
                "document_version": command.document_version_after,
                "chapter_ids": sorted(chapter_ids),
            },
        )
    )
    connection.execute(
        update(ApprovalRecord.__table__)
        .where(base)
        .values(
            status="stale",
            invalidated_at=now,
            invalidated_reason=(
                f"Approval became outdated after {command.command_type} at document "
                f"version {command.document_version_after}."
            ),
            invalidated_by_event_id=event_id,
        )
    )
