"""Pandoc universal interop API (enterprise E6).

Export the rendered manuscript to extra formats, and a non-mutating preview
converter for uploaded documents. Owner-guarded. Binary results are returned
base64-encoded. Fail-closed: pandoc unavailable -> 503; bad format -> 422.
"""

from __future__ import annotations

import base64
import binascii
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, fetch_owned_project
from app.db.deps import get_db
from app.interop.pandoc import (
    BINARY_OUTPUTS,
    INPUT_FORMATS,
    OUTPUT_FORMATS,
    PandocError,
    PandocUnavailableError,
    convert,
    pandoc_available,
)
from app.models.source import Source
from app.renderers.md_renderer import render_md
from app.services.export_service import _resolve_project_profile, build_thesis_document

router = APIRouter(tags=["projects"])

_MAX_INPUT_BYTES = 10 * 1024 * 1024


class ExportPandocRequest(BaseModel):
    to: str = "odt"


class ConvertPreviewRequest(BaseModel):
    content: str | None = None
    content_base64: str | None = None
    from_fmt: str = "markdown"
    to_fmt: str = "html"


def _encode(data: bytes, fmt: str) -> dict:
    if fmt in BINARY_OUTPUTS:
        return {"encoding": "base64", "content": base64.b64encode(data).decode("ascii")}
    return {"encoding": "utf-8", "content": data.decode("utf-8", "replace")}


@router.get("/interop/formats")
async def interop_formats(current_user: CurrentUser) -> dict:
    """Supported pandoc formats and whether conversion is available."""
    return {
        "available": pandoc_available(),
        "input_formats": sorted(INPUT_FORMATS),
        "output_formats": sorted(OUTPUT_FORMATS),
        "binary_outputs": sorted(BINARY_OUTPUTS),
    }


@router.post("/projects/{project_id}/export/pandoc")
async def export_pandoc(
    project_id: UUID,
    body: ExportPandocRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Render the manuscript to Markdown, then convert to the requested format."""
    if not pandoc_available():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Document conversion is not available on this deployment.",
        )
    project = await fetch_owned_project(db, project_id, current_user.id)
    document = build_thesis_document(project)
    rows = list(
        (await db.execute(select(Source).where(Source.project_id == project.id))).scalars()
    )
    sources = {row.id: row for row in rows}
    profile, _ = await _resolve_project_profile(db, project)
    markdown = render_md(document, sources, profile)

    try:
        data = await convert(markdown, from_fmt="markdown", to_fmt=body.to)
    except PandocUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except PandocError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    return {"format": body.to, "source_format": "markdown", **_encode(data, body.to)}


@router.post("/interop/convert/preview")
async def convert_preview(
    body: ConvertPreviewRequest,
    current_user: CurrentUser,
) -> dict:
    """Convert supplied content between formats. Non-mutating; nothing persisted."""
    if not pandoc_available():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Document conversion is not available on this deployment.",
        )
    if body.content is not None:
        raw: bytes = body.content.encode("utf-8")
    elif body.content_base64:
        try:
            raw = base64.b64decode(body.content_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid base64 content."
            ) from exc
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Provide content or content_base64."
        )
    if len(raw) > _MAX_INPUT_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Input exceeds the 10 MB limit.",
        )

    try:
        data = await convert(raw, from_fmt=body.from_fmt, to_fmt=body.to_fmt)
    except PandocUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except PandocError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    return {"from": body.from_fmt, "to": body.to_fmt, **_encode(data, body.to_fmt)}
