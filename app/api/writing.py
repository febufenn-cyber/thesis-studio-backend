"""Writing-quality API (enterprise E7).

Advisory grammar/style suggestions from LanguageTool. Owner-guarded and
non-mutating: it returns suggested edits with positions; it never rewrites the
manuscript or changes any verification state. Fail-closed when the checker is
disabled or unreachable.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, fetch_owned_project
from app.core.config import get_settings
from app.db.deps import get_db
from app.references.http import build_client
from app.writing.languagetool import check_text

router = APIRouter(tags=["projects"])

_MAX_CHARS = 40_000


class WritingCheckRequest(BaseModel):
    text: str = Field(default="", max_length=_MAX_CHARS)
    language: str | None = None


@router.get("/writing/status")
async def writing_status(current_user: CurrentUser) -> dict:
    """Whether private writing checks are configured."""
    settings = get_settings()
    return {
        "enabled": bool(getattr(settings, "LANGUAGETOOL_ENABLED", False)),
        "configured": bool(getattr(settings, "LANGUAGETOOL_URL", "")),
        "language": getattr(settings, "LANGUAGETOOL_LANGUAGE", "en-US"),
    }


@router.post("/projects/{project_id}/writing/check")
async def check_project_text(
    project_id: UUID,
    body: WritingCheckRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return advisory grammar/style suggestions for the supplied text."""
    # Owner guard: the project must belong to the caller even though the text is
    # supplied inline (keeps the feature scoped to a user's own work).
    await fetch_owned_project(db, project_id, current_user.id)

    settings = get_settings()
    if not getattr(settings, "LANGUAGETOOL_ENABLED", False):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Writing checks are not enabled on this deployment.",
        )

    client = build_client()
    try:
        result = await check_text(client, body.text, language=body.language)
    finally:
        await client.aclose()
    return {"advisory": True, **result}
