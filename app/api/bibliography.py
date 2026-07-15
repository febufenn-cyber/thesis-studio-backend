"""Bibliography rendering API (enterprise E5).

Renders a project's registry sources into a formatted bibliography in any of the
10,000+ Citation Style Language styles, via the citeproc engine. Read-only and
owner-guarded. A formatter, never a fact source: only registry fields are
rendered, and an unresolvable style fails closed with a clear error rather than a
substituted or invented bibliography.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, fetch_owned_project
from app.core.config import get_settings
from app.db.deps import get_db
from app.models.source import Source
from app.references.csl_render import CSLRenderError, render_bibliography
from app.references.csl_styles import STYLE_ALIASES, friendly_style_id, resolve_style_xml
from app.references.http import build_client
from app.renderers.csl import to_csl_json

router = APIRouter(tags=["projects"])


class RenderBibliographyRequest(BaseModel):
    style: str = "harvard1"
    output: str = "html"  # "html" | "text"


@router.get("/bibliography/styles")
async def bibliography_styles(current_user: CurrentUser) -> dict:
    """Friendly style aliases plus the offline-bundled default."""
    return {
        "bundled": "harvard1",
        "aliases": sorted(STYLE_ALIASES.keys()),
        "note": "Any style id from the CSL styles repository is also accepted.",
    }


@router.post("/projects/{project_id}/bibliography/render")
async def render_project_bibliography(
    project_id: UUID,
    body: RenderBibliographyRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Render the project's sources as a bibliography in the requested style."""
    project = await fetch_owned_project(db, project_id, current_user.id)
    rows = list(
        (await db.execute(select(Source).where(Source.project_id == project.id))).scalars()
    )
    items = to_csl_json(rows)

    enabled = bool(getattr(get_settings(), "CSL_ENABLED", True))
    client = build_client()
    try:
        style_xml = await resolve_style_xml(client, body.style, enabled=enabled)
    finally:
        await client.aclose()
    if style_xml is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Citation style '{body.style}' could not be resolved. "
                "Check the style id, or enable style fetching."
            ),
        )

    try:
        entries = render_bibliography(items, style_xml, output=body.output)
    except CSLRenderError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    return {
        "style": friendly_style_id(body.style),
        "requested_style": body.style,
        "output": body.output,
        "count": len(entries),
        "entries": entries,
    }
