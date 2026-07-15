"""Interchange export/import API (docs/LLD.md 3.5).

Read-only exports (JATS / LaTeX / CSL-JSON) rendered directly from the canonical
document, plus a non-mutating LaTeX import *preview* that parses an ``article``
subset and returns the canonical structure without persisting. Owner-guarded.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, fetch_owned_project
from app.db.deps import get_db
from app.importers.latex_import import UnsupportedLatexError, from_latex
from app.models.source import Source
from app.renderers.csl import to_csl_json
from app.renderers.docx_renderer import RenderError
from app.renderers.jats import to_jats
from app.renderers.latex import to_latex
from app.services.export_service import build_thesis_document

router = APIRouter(tags=["projects"])

_MAX_CONTENT_BYTES = 2 * 1024 * 1024


class LatexImportRequest(BaseModel):
    content: str


async def _document_and_sources(db: AsyncSession, project):
    document = build_thesis_document(project)
    rows = list(
        (await db.execute(select(Source).where(Source.project_id == project.id))).scalars()
    )
    sources = {row.id: row for row in rows}
    return document, sources


@router.get("/projects/{project_id}/export/jats")
async def export_jats(
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Render the project to JATS XML."""
    project = await fetch_owned_project(db, project_id, current_user.id)
    document, sources = await _document_and_sources(db, project)
    try:
        xml = to_jats(document, sources)
    except RenderError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return {"format": "jats", "content": xml}


@router.get("/projects/{project_id}/export/latex")
async def export_latex(
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Render the project to a LaTeX article."""
    project = await fetch_owned_project(db, project_id, current_user.id)
    document, sources = await _document_and_sources(db, project)
    return {"format": "latex", "content": to_latex(document, sources)}


@router.get("/projects/{project_id}/export/csl")
async def export_csl(
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Serialize the project's sources to CSL-JSON."""
    project = await fetch_owned_project(db, project_id, current_user.id)
    rows = list(
        (await db.execute(select(Source).where(Source.project_id == project.id))).scalars()
    )
    return {"format": "csl", "items": to_csl_json(rows)}


@router.post("/projects/{project_id}/import/latex/preview")
async def import_latex_preview(
    project_id: UUID,
    body: LatexImportRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Parse a LaTeX article subset into canonical structure (no persistence)."""
    await fetch_owned_project(db, project_id, current_user.id)
    if len(body.content.encode("utf-8")) > _MAX_CONTENT_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="LaTeX payload exceeds the 2 MB limit.",
        )
    try:
        document = from_latex(body.content)
    except UnsupportedLatexError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported LaTeX macro: {exc.args[0]}",
        ) from exc

    paragraphs = 0
    unresolved_citations = 0
    for chapter in document.chapters:
        for block in chapter.blocks:
            if block.type == "paragraph":
                paragraphs += 1
            elif block.type == "marker" and getattr(block, "kind", "") == "SOURCE_NEEDED":
                unresolved_citations += 1
    return {
        "title": document.meta.title,
        "chapters": len(document.chapters),
        "paragraphs": paragraphs,
        "unresolved_citations": unresolved_citations,
        "document": document.model_dump(mode="json"),
    }
