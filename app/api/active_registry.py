"""Read-only active registry endpoints for the Phase 1 operator workspace."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, fetch_owned_project
from app.db.deps import get_db
from app.models.citation_resolution import CitationResolution
from app.models.quote import Quote
from app.models.source import Source
from app.schemas.project import QuoteResponse, SourceResponse
from app.services.registry_scope import active_resolution_rows, active_revision_rows


router = APIRouter(tags=["phase1"])


@router.get(
    "/projects/{project_id}/active-sources",
    response_model=list[SourceResponse],
)
async def list_active_sources(
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    project = await fetch_owned_project(db, project_id, current_user.id)
    rows = list(
        (
            await db.execute(
                select(Source)
                .where(
                    Source.project_id == project.id,
                    Source.user_id == current_user.id,
                )
                .order_by(Source.created_at.asc())
            )
        ).scalars()
    )
    return active_revision_rows(rows, project.active_revision_id)


@router.get(
    "/projects/{project_id}/active-quotes",
    response_model=list[QuoteResponse],
)
async def list_active_quotes(
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    project = await fetch_owned_project(db, project_id, current_user.id)
    rows = list(
        (
            await db.execute(
                select(Quote)
                .where(
                    Quote.project_id == project.id,
                    Quote.user_id == current_user.id,
                )
                .order_by(Quote.created_at.asc())
            )
        ).scalars()
    )
    return active_revision_rows(rows, project.active_revision_id)


@router.get("/projects/{project_id}/active-citation-resolutions")
async def list_active_resolutions(
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    project = await fetch_owned_project(db, project_id, current_user.id)
    rows = list(
        (
            await db.execute(
                select(CitationResolution)
                .where(
                    CitationResolution.project_id == project.id,
                    CitationResolution.user_id == current_user.id,
                )
                .order_by(CitationResolution.created_at.asc())
            )
        ).scalars()
    )
    return [
        {
            "id": str(row.id),
            "revision_id": str(row.revision_id) if row.revision_id else None,
            "block_id": str(row.block_id),
            "raw_citation": row.raw_citation,
            "source_id": str(row.source_id),
            "created_at": row.created_at,
        }
        for row in active_resolution_rows(rows, project.active_revision_id)
    ]
