"""Authoritative rendered preview API."""

from __future__ import annotations

import os
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, fetch_owned_project
from app.db.deps import get_db
from app.models.document_preview import DocumentPreview
from app.schemas.editor import PreviewRequest
from app.services.preview_service import StalePreviewError, request_preview
from app.services.storage_service import get_storage_service


router = APIRouter(tags=["phase2-preview"])


def _response(row: DocumentPreview, current_version: int) -> dict:
    return {
        "id": str(row.id),
        "document_version": row.document_version,
        "manuscript_revision_id": (
            str(row.manuscript_revision_id) if row.manuscript_revision_id else None
        ),
        "profile_version": row.profile_version,
        "status": row.status,
        "checksum": row.checksum,
        "size_bytes": row.size_bytes,
        "page_count": row.page_count,
        "error_message": row.error_message,
        "manifest": row.manifest or {},
        "stale": row.document_version != current_version,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@router.post("/projects/{project_id}/previews", status_code=202)
async def create_or_get_preview(
    project_id: UUID,
    body: PreviewRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    project = await fetch_owned_project(db, project_id, current_user.id)
    try:
        row = await request_preview(
            db,
            project,
            current_user.id,
            expected_version=body.expected_document_version,
            force=body.force,
        )
    except StalePreviewError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return _response(row, project.document_version)


@router.get("/projects/{project_id}/previews")
async def list_previews(
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    project = await fetch_owned_project(db, project_id, current_user.id)
    rows = list(
        (
            await db.execute(
                select(DocumentPreview)
                .where(
                    DocumentPreview.project_id == project.id,
                    DocumentPreview.user_id == current_user.id,
                )
                .order_by(DocumentPreview.created_at.desc())
                .limit(50)
            )
        ).scalars()
    )
    return [_response(row, project.document_version) for row in rows]


@router.get("/previews/{preview_id}")
async def get_preview(
    preview_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    row = (
        await db.execute(
            select(DocumentPreview).where(
                DocumentPreview.id == preview_id,
                DocumentPreview.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Preview not found")
    project = await fetch_owned_project(db, row.project_id, current_user.id)
    return _response(row, project.document_version)


@router.get("/previews/{preview_id}/file", response_model=None)
async def stream_preview_file(
    preview_id: UUID,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    row = (
        await db.execute(
            select(DocumentPreview).where(
                DocumentPreview.id == preview_id,
                DocumentPreview.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Preview not found")
    if row.status != "ready" or not row.storage_key:
        raise HTTPException(status_code=409, detail="Preview is not ready")
    storage = get_storage_service()
    try:
        path = await storage.open_local_path(row.storage_key)
    except NotImplementedError:
        path = await storage.download_to_temp(row.storage_key)
        background_tasks.add_task(os.unlink, path)
    return FileResponse(
        path,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="preview-v{row.document_version}.pdf"',
            "Cache-Control": "private, max-age=300",
            "ETag": row.checksum or "",
        },
    )
