"""AI provenance API — rollup, timeline, and AI Use Statement generation.

Owner-guarded (foreign project → 404). Statement generation fails closed on an
unknown disclosure template (409) rather than emitting a generic statement.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, fetch_owned_project
from app.db.deps import get_db
from app.models.ai_use_statement import AIUseStatement
from app.provenance.rollup import build_rollup
from app.provenance.templates import UnknownDisclosureTemplate, list_disclosure_templates
from app.services.provenance_service import (
    generate_ai_use_statement,
    get_latest_statement,
    get_provenance_timeline,
)

router = APIRouter(tags=["provenance"])


class AIUseStatementRequest(BaseModel):
    template_key: str | None = None
    granularity: str = "document"


def _statement_dict(statement: AIUseStatement) -> dict:
    return {
        "id": str(statement.id),
        "template_key": statement.template_key,
        "granularity": statement.granularity,
        "body_text": statement.body_text,
        "content_hash": statement.content_hash,
        "document_version": statement.document_version,
        "document_checksum": statement.document_checksum,
        "rollup": statement.rollup,
        "created_at": statement.created_at.isoformat() if statement.created_at else None,
    }


@router.get("/projects/{project_id}/provenance/summary")
async def provenance_summary(
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Per-origin block counts and accepted-proposal history for the project."""
    project = await fetch_owned_project(db, project_id, current_user.id)
    rollup = await build_rollup(db, project, document_version=project.document_version)
    return {
        "document_version": project.document_version,
        "rollup": rollup.to_dict(),
        "templates": list_disclosure_templates(),
    }


@router.get("/projects/{project_id}/provenance/timeline")
async def provenance_timeline(
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Ordered accepted-proposal authorship events."""
    project = await fetch_owned_project(db, project_id, current_user.id)
    events = await get_provenance_timeline(db, project)
    return {"document_version": project.document_version, "events": events}


@router.post("/projects/{project_id}/ai-use-statement", status_code=status.HTTP_201_CREATED)
async def create_ai_use_statement(
    project_id: UUID,
    body: AIUseStatementRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Generate and persist an AI Use Statement for the current document version."""
    project = await fetch_owned_project(db, project_id, current_user.id)
    try:
        statement = await generate_ai_use_statement(
            db,
            project,
            template_key=body.template_key,
            granularity=body.granularity,
            generated_by=current_user.id,
        )
    except UnknownDisclosureTemplate as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Unknown disclosure template: {exc.args[0]}",
        ) from exc
    await db.commit()
    return _statement_dict(statement)


@router.get("/projects/{project_id}/ai-use-statement")
async def read_ai_use_statement(
    project_id: UUID,
    current_user: CurrentUser,
    version: int | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return the most recent AI Use Statement (optionally for a version)."""
    project = await fetch_owned_project(db, project_id, current_user.id)
    statement = await get_latest_statement(db, project, document_version=version)
    if statement is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No AI Use Statement has been generated for this project.",
        )
    return _statement_dict(statement)
