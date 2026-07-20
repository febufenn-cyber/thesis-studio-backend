"""Research copilot API (enterprise E3).

Paper insight (TLDR, impact, related work) for a registry source. Advisory,
owner-guarded, fail-closed.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, fetch_owned_project
from app.core.config import get_settings
from app.core.rate_limit import limiter
from app.db.deps import get_db
from app.models.source import Source
from app.references.copilot import paper_insight
from app.references.http import build_client

router = APIRouter(tags=["projects"])


@router.get("/projects/{project_id}/sources/{source_id}/insight")
@limiter.limit(lambda: get_settings().RATE_LIMIT_LOOKUP)
async def source_insight(
    request: Request,
    project_id: UUID,
    source_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """TLDR summary, impact, and related work for a source (advisory)."""
    project = await fetch_owned_project(db, project_id, current_user.id)
    source = (
        await db.execute(
            select(Source).where(Source.id == source_id, Source.project_id == project.id)
        )
    ).scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found.")

    fields = source.fields or {}
    doi = str(fields.get("doi_or_url") or (source.identifiers or {}).get("doi") or "").strip()
    if not getattr(get_settings(), "COPILOT_ENABLED", True):
        return {"advisory": True, "found": False, "tldr": None, "references": [], "citations": []}
    client = build_client()
    try:
        insight = await paper_insight(client, doi)
    finally:
        await client.aclose()
    return {"advisory": True, **insight}
