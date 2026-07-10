"""Compile router — trigger a thesis compile job and retrieve generated files.

Endpoints:
  POST /sessions/{session_id}/compile   — start a background compile; returns 202
  GET  /sessions/{session_id}/files     — list files for a session, newest first
  GET  /files/{file_id}/download        — redirect to presigned URL or serve directly

Per-user isolation contract:
  - fetch_owned_session gates the session endpoints (404 on mismatch/archive).
  - The download endpoint filters by user_id directly (no session context needed).
  - Cross-user access always returns 404, never 403.
"""

from __future__ import annotations

import re
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import FileResponse as FileDownloadResponse
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, fetch_owned_session
from app.db.deps import get_db
from app.models.file import FILE_TYPE_DOCX, File
from app.models.message import ROLE_ASSISTANT, Message
from app.schemas.file import CompileTriggerResponse, FileResponse
from app.services.compile_service import run_compile
from app.services.storage_service import get_storage_service


router = APIRouter(tags=["compile"])


@router.post(
    "/sessions/{session_id}/compile",
    response_model=CompileTriggerResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_compile(
    session_id: UUID,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> CompileTriggerResponse:
    """Trigger an asynchronous thesis compile for this session.

    Returns 202 immediately.  The compile job runs in the background;
    poll GET /sessions/{session_id}/files to check status.

    Raises:
      409 if there are no assistant messages yet (nothing to compile).
      409 if a compile job is already running for this session.
    """
    session = await fetch_owned_session(db, session_id, current_user.id)

    # Guard: refuse if the coaching conversation has not started yet.
    has_reply = await db.execute(
        select(Message.id)
        .where(Message.session_id == session.id)
        .where(Message.role == ROLE_ASSISTANT)
        .limit(1)
    )
    if has_reply.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Nothing to compile yet — have a coaching conversation first.",
        )

    # Guard: serialise compiles (one at a time per session).
    in_progress = await db.execute(
        select(File.id)
        .where(File.session_id == session.id)
        .where(File.status == "compiling")
        .limit(1)
    )
    if in_progress.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A compile is already running for this session.",
        )

    # Build a human-readable filename using the user's last name. The name is
    # whitelisted to filename-safe characters because it ends up inside a
    # Content-Disposition header (both locally and in the presigned R2 URL).
    name_parts = (current_user.full_name or "").split()
    last_name = re.sub(r"[^A-Za-z0-9_-]", "", name_parts[-1]) if name_parts else ""
    filename = (
        f"{last_name or 'Thesis'}_MA_Dissertation_"
        f"{datetime.now().strftime('%Y%m%d_%H%M')}.docx"
    )

    file = File(
        session_id=session.id,
        user_id=current_user.id,
        filename=filename,
        file_type=FILE_TYPE_DOCX,
        r2_key=None,
        status="compiling",
    )
    db.add(file)
    await db.commit()
    await db.refresh(file)

    background_tasks.add_task(run_compile, file.id, session.id, current_user.id)

    return CompileTriggerResponse(
        file_id=file.id,
        filename=file.filename,
        status=file.status,
    )


@router.get(
    "/sessions/{session_id}/files",
    response_model=list[FileResponse],
)
async def list_files(
    session_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> list[File]:
    """List all compiled files for a session, newest first."""
    # Ownership check — must come before the query so cross-user probing returns 404.
    await fetch_owned_session(db, session_id, current_user.id)

    result = await db.execute(
        select(File)
        .where(File.session_id == session_id)
        .where(File.user_id == current_user.id)
        .order_by(File.created_at.desc())
    )
    return list(result.scalars().all())


@router.get("/files/{file_id}/download", response_model=None)
async def download_file(
    file_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse | FileDownloadResponse:
    """Download a compiled file.

    Redirects to a presigned R2 URL (307) when R2 is the active backend.
    Falls back to serving the file directly for the local-filesystem backend.

    Raises:
      404 if the file does not exist or belongs to another user.
      409 if the file is not yet ready (status != "ready").
    """
    result = await db.execute(
        select(File)
        .where(File.id == file_id)
        .where(File.user_id == current_user.id)
    )
    file_row = result.scalar_one_or_none()
    if file_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="File not found"
        )

    if file_row.status != "ready":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="File is not ready."
        )

    storage = get_storage_service()
    url = await storage.presigned_download_url(file_row.r2_key, file_row.filename)
    if url:
        return RedirectResponse(url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)

    # Local backend: serve the bytes directly.
    local_path = await storage.open_local_path(file_row.r2_key)
    return FileDownloadResponse(
        local_path,
        filename=file_row.filename,
        media_type=(
            "application/vnd.openxmlformats-officedocument"
            ".wordprocessingml.document"
        ),
    )
