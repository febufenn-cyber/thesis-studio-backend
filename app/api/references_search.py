"""Literature discovery API (docs/LLD_MISSING_FEATURES.md MF1).

Search upstream authorities and add a result as a verified registry source.
Owner-guarded, dual-mounted. Added sources are resolver-verified, never guessed.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, fetch_owned_project
from app.db.deps import get_db
from app.references.search import add_candidate, search
from app.renderers.field_schema import missing_required

router = APIRouter(tags=["projects"])


class AddCandidateRequest(BaseModel):
    identifier: str


@router.get("/projects/{project_id}/references/search")
async def references_search(
    project_id: UUID,
    current_user: CurrentUser,
    q: str,
    limit: int = 10,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Search OpenAlex + Crossref for candidate references."""
    await fetch_owned_project(db, project_id, current_user.id)
    candidates = await search(db, q, limit=max(1, min(limit, 25)))
    return {"candidates": [c.to_dict() for c in candidates]}


@router.post("/projects/{project_id}/references/search/add")
async def add_search_result(
    project_id: UUID,
    body: AddCandidateRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Resolve and add a discovered result as a verified registry source."""
    project = await fetch_owned_project(db, project_id, current_user.id)
    source, applied = await add_candidate(db, project, current_user.id, body.identifier)
    still_missing = missing_required(source.kind, source.fields or {})
    await db.commit()
    return {
        "source_id": str(source.id),
        "applied_fields": applied,
        "resolution_status": source.resolution_status,
        "retraction_status": source.retraction_status,
        "still_missing": still_missing,
    }
