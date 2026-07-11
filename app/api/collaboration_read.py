"""Capability-aware project reads for the shared Phase 4 workspace shell."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.canonical.migrations import project_payload
from app.canonical.model import HeadingBlock, ThesisDocument
from app.collaboration.capabilities import require_project_capability
from app.db.deps import get_db
from app.models.export import Export


router = APIRouter(tags=["collaboration"])


def _heading_nodes(chapter) -> list[dict]:
    return [
        {"id": str(block.id), "level": block.level, "text": block.text}
        for block in chapter.blocks
        if isinstance(block, HeadingBlock)
    ]


@router.get("/projects/{project_id}/collaboration/project")
async def shared_project(
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    access = await require_project_capability(db, project_id, current_user, "project.read_metadata")
    project = access.project
    result = {
        "id": project.id,
        "user_id": project.user_id,
        "institution_id": project.institution_id,
        "department_id": project.department_id,
        "title": project.title,
        "mode": project.mode,
        "doc_type": project.doc_type,
        "status": project.status,
        "workflow_state": project.workflow_state,
        "format_profile": project.format_profile,
        "style_profile_id": project.style_profile_id,
        "institutional_profile_version_id": project.institutional_profile_version_id,
        "institutional_policy_version_id": project.institutional_policy_version_id,
        "active_revision_id": project.active_revision_id,
        "document_version": project.document_version,
        "canonical_schema_version": project.canonical_schema_version,
        "submission_locked": project.submission_locked,
        "archived": project.archived,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
        "role": access.role,
        "capabilities": sorted(access.capabilities),
        "content_access": access.content_access,
        "source_access": access.source_access,
        "ai_history_access": access.ai_history_access,
    }
    if access.content_access:
        result.update(
            {
                "meta": project.meta,
                "front_matter": project.front_matter,
                "chapters": project.chapters,
                "works_cited": project.works_cited,
            }
        )
    else:
        result.update({"meta": {}, "front_matter": [], "chapters": [], "works_cited": []})
    return result


@router.get("/projects/{project_id}/collaboration/structure")
async def shared_structure(
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    access = await require_project_capability(db, project_id, current_user, "project.read_metadata")
    project = access.project
    if not access.content_access:
        return {
            "project": {
                "id": str(project.id),
                "title": project.title,
                "document_version": project.document_version,
                "canonical_schema_version": project.canonical_schema_version,
                "format_profile": project.format_profile,
                "active_revision_id": str(project.active_revision_id) if project.active_revision_id else None,
                "workflow_state": project.workflow_state,
                "role": access.role,
                "content_access": False,
            },
            "front_matter": [],
            "chapters": [],
            "works_cited_count": 0,
            "exports": [],
        }
    document = ThesisDocument.model_validate(project_payload(project))
    exports = list(
        (
            await db.execute(
                select(Export).where(
                    Export.project_id == project.id,
                    Export.status == "ready",
                )
            )
        ).scalars()
    )
    return {
        "project": {
            "id": str(project.id),
            "title": project.title,
            "document_version": project.document_version,
            "canonical_schema_version": project.canonical_schema_version,
            "format_profile": project.format_profile,
            "active_revision_id": str(project.active_revision_id) if project.active_revision_id else None,
            "workflow_state": project.workflow_state,
            "role": access.role,
            "content_access": True,
        },
        "front_matter": [
            {
                "id": str(entry.id),
                "kind": entry.kind,
                "status": entry.status,
                "block_count": len(entry.body_blocks),
            }
            for entry in document.front_matter
        ],
        "chapters": [
            {
                "id": str(chapter.id),
                "number": chapter.number,
                "title": chapter.title,
                "status": chapter.status,
                "block_count": len(chapter.blocks),
                "headings": _heading_nodes(chapter),
            }
            for chapter in document.chapters
        ],
        "works_cited_count": len(document.works_cited),
        "exports": [
            {
                "id": str(row.id),
                "format": row.format,
                "document_version": row.document_version,
                "status": row.status,
                "stale": row.document_version != project.document_version,
                "manifest_state": (row.manifest or {}).get("state"),
                "created_at": row.created_at.isoformat(),
            }
            for row in exports
        ],
    }


@router.get("/projects/{project_id}/collaboration/current-document")
async def shared_current_document(
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    access = await require_project_capability(db, project_id, current_user, "project.read_content")
    return {
        "project_id": project_id,
        "document_version": access.project.document_version,
        "canonical_document": project_payload(access.project),
        "private_ai_history_included": False,
    }
