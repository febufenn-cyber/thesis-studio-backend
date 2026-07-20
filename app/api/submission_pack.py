"""Submission Pack API — one click, one zip (the sellable unit).

Owner-guarded, rate-limited (renders a PDF inline). Review packs are honest:
UNVERIFIED markers intact and manifest.state == "review"; nothing is ever
marked verified by packing.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, fetch_owned_project
from app.core.config import get_settings
from app.core.rate_limit import limiter
from app.db.deps import get_db
from app.renderers.docx_renderer import RenderError
from app.renderers.pdf_renderer import PdfConversionError, SofficeUnavailableError
from app.services.submission_pack import build_submission_pack

router = APIRouter(tags=["projects"])


@router.post("/projects/{project_id}/submission-pack")
@limiter.limit(lambda: get_settings().RATE_LIMIT_EXPENSIVE)
async def download_submission_pack(
    request: Request,
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Build and return the Submission Pack zip for this project."""
    project = await fetch_owned_project(db, project_id, current_user.id)
    try:
        data, manifest = await build_submission_pack(db, project, current_user.id)
    except SofficeUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PDF rendering is not available on this deployment.",
        ) from exc
    except (RenderError, PdfConversionError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    await db.commit()  # persists the generated AI-use statement row
    filename = f"submission-pack-{manifest['state']}-v{manifest['document_version']}.zip"
    return Response(
        content=data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Pack-State": manifest["state"],
        },
    )
