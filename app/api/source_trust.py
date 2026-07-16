"""Source & Journal Trust API (enterprise E1).

Advisory "is this source safe to cite?" verdict from free indexing signals.
Owner-guarded; never changes a verified bit.
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
from app.references.trust import assess_source_trust

router = APIRouter(tags=["projects"])


@router.get("/projects/{project_id}/sources/{source_id}/trust")
@limiter.limit(lambda: get_settings().RATE_LIMIT_LOOKUP)
async def source_trust(
    request: Request,
    project_id: UUID,
    source_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Advisory journal/source trust report (indexing, retraction, self-archiving)."""
    project = await fetch_owned_project(db, project_id, current_user.id)
    source = (
        await db.execute(
            select(Source).where(Source.id == source_id, Source.project_id == project.id)
        )
    ).scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found.")
    report = await assess_source_trust(db, source)
    return {"source_id": str(source.id), **report}
