"""Role-bounded access to the Phase 2 command engine.

Students retain authorship control. Operators may correct metadata and structure,
but this bridge mechanically rejects prose rewrites. Supervisors use comments and
structured suggestions rather than silently editing student text.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.collaboration.capabilities import require_project_capability
from app.db.deps import get_db
from app.editor.commands import CommandError
from app.schemas.editor import CommandRequest
from app.services.editor_service import VersionConflict, apply_project_command
from app.services.review_service import sync_review_items


router = APIRouter(tags=["collaboration"])


_STUDENT_COMMANDS = {
    "update_metadata", "reorder_chapters", "reorder_front_matter", "update_chapter",
    "set_chapter_status", "set_front_matter_status", "update_front_matter_body",
    "insert_block", "restore_block_original", "update_block", "update_block_text",
    "change_block_type", "delete_block", "duplicate_block", "move_block",
    "split_block", "merge_blocks", "add_marker",
}
_OPERATOR_METADATA_COMMANDS = {
    "update_metadata", "reorder_front_matter", "set_front_matter_status",
}
_OPERATOR_STRUCTURE_COMMANDS = {
    "reorder_chapters", "update_chapter", "set_chapter_status", "reorder_front_matter",
    "set_front_matter_status", "change_block_type", "move_block", "split_block",
    "merge_blocks", "add_marker",
}
_OPERATOR_PROSE_COMMANDS = {
    "update_block", "update_block_text", "insert_block", "delete_block",
    "duplicate_block", "update_front_matter_body", "restore_block_original",
}


def permitted_command(role: str, capabilities: frozenset[str], command_type: str) -> bool:
    if role == "student" and "project.edit_content" in capabilities:
        return command_type in _STUDENT_COMMANDS
    if role == "operator":
        if command_type in _OPERATOR_PROSE_COMMANDS:
            return False
        if command_type in _OPERATOR_METADATA_COMMANDS and "project.edit_metadata" in capabilities:
            return True
        if command_type in _OPERATOR_STRUCTURE_COMMANDS and "project.edit_structure" in capabilities:
            return True
    return False


@router.post("/projects/{project_id}/collaboration/commands")
async def apply_collaboration_command(
    project_id: UUID,
    body: CommandRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    access = await require_project_capability(db, project_id, current_user, "project.read_metadata")
    if access.project.submission_locked:
        raise HTTPException(
            status_code=409,
            detail="The sealed submission is immutable. Withdraw it or start a post-submission revision.",
        )
    if not permitted_command(access.role, access.capabilities, body.command_type):
        if access.role == "operator" and body.command_type in _OPERATOR_PROSE_COMMANDS:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Formatting operators cannot rewrite academic prose. Create a structured suggestion "
                    "for student acceptance instead."
                ),
            )
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        command, result = await apply_project_command(
            db,
            access.project,
            current_user.id,
            command_type=body.command_type,
            payload=body.payload,
            expected_version=body.expected_document_version,
            client_request_id=body.client_request_id,
            batch_id=body.batch_id,
            summary=body.summary,
        )
        await sync_review_items(db, access.project)
        await db.commit()
    except VersionConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": str(exc),
                "expected_version": exc.expected,
                "current_version": exc.current,
            },
        ) from None
    except CommandError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return {
        "command": {
            "id": command.id,
            "command_type": command.command_type,
            "summary": command.summary,
            "target_type": command.target_type,
            "target_id": command.target_id,
            "document_version_before": command.document_version_before,
            "document_version_after": command.document_version_after,
            "created_at": command.created_at,
        },
        "document_version": access.project.document_version,
        "changed_block_ids": sorted(result.changed_block_ids, key=str),
        "changed_chapter_ids": sorted(result.changed_chapter_ids, key=str),
        "invalidations": result.invalidations,
        "authority": {
            "actor_role": access.role,
            "student_authorship_preserved": True,
            "operator_prose_rewrite_allowed": False,
        },
    }
