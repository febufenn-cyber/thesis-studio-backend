"""Phase 1 manuscript, revision, review and verification API."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse as FileDownloadResponse
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, fetch_owned_project
from app.db.deps import get_db
from app.ingest.preflight import DOCX_MIME, MAX_UPLOAD_BYTES, ManuscriptValidationError, inspect_docx
from app.models.event import Event
from app.models.job import Job
from app.models.manuscript_revision import ManuscriptRevision
from app.models.quote import Quote
from app.models.source import Source
from app.schemas.project import (
    JobResponse,
    ManuscriptRevisionResponse,
    ManuscriptUploadResponse,
    ProjectDetailResponse,
    RevisionApplyRequest,
    SourceResponse,
    SourceUpdate,
    VerificationResponse,
)
from app.services.job_queue import enqueue_job
from app.services.manuscript_service import IngestionError, apply_revision
from app.services.storage_service import get_storage_service
from app.services.verification_service import verify_project


router = APIRouter(tags=["phase1"])
_ALLOWED_MIMES = {DOCX_MIME, "application/octet-stream", "application/zip"}


class IssueResolution(BaseModel):
    resolution: str = Field(..., min_length=2, max_length=1000)
    expected_version: int = Field(..., ge=1)


class QuoteVerificationUpdate(BaseModel):
    verified: bool
    verification_method: str = Field("manual", min_length=2, max_length=40)
    expected_text: str | None = None


def _assert_version(project, expected: int) -> None:
    if project.document_version != expected:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Project changed in another session. Reload before continuing.",
                "expected_version": expected,
                "current_version": project.document_version,
            },
        )


def _safe_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value)[:180] or "manuscript.docx"


@router.post(
    "/projects/{project_id}/manuscript",
    response_model=ManuscriptUploadResponse,
    status_code=202,
)
async def upload_manuscript(
    project_id: UUID,
    current_user: CurrentUser,
    file: UploadFile = File(...),
    apply_when_ready: bool = Form(True),
    force_duplicate: bool = Form(False),
    db: AsyncSession = Depends(get_db),
) -> ManuscriptUploadResponse:
    """Stream a DOCX upload, preserve it immutably, and enqueue ingestion."""

    project = await fetch_owned_project(db, project_id, current_user.id)
    filename = _safe_filename(file.filename or "manuscript.docx")
    if not filename.lower().endswith(".docx"):
        raise HTTPException(status_code=422, detail="Only .docx manuscripts are accepted.")
    if file.content_type and file.content_type not in _ALLOWED_MIMES:
        raise HTTPException(status_code=422, detail="The upload content type is not a DOCX document.")

    descriptor, temp_path = tempfile.mkstemp(prefix="manuscript_", suffix=".docx")
    os.close(descriptor)
    digest = hashlib.sha256()
    size_bytes = 0
    storage_key: str | None = None
    storage = get_storage_service()
    try:
        with open(temp_path, "wb") as output:
            while True:
                chunk = await file.read(64 * 1024)
                if not chunk:
                    break
                size_bytes += len(chunk)
                if size_bytes > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"The manuscript exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.",
                    )
                digest.update(chunk)
                output.write(chunk)
        checksum = digest.hexdigest()
        try:
            inspect_docx(temp_path)
        except ManuscriptValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None

        duplicate = (
            await db.execute(
                select(ManuscriptRevision)
                .where(
                    ManuscriptRevision.project_id == project.id,
                    ManuscriptRevision.user_id == current_user.id,
                    ManuscriptRevision.checksum == checksum,
                )
                .order_by(ManuscriptRevision.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if duplicate is not None and not force_duplicate:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "This exact manuscript was already uploaded.",
                    "duplicate_revision_id": str(duplicate.id),
                    "revision_number": duplicate.revision_number,
                },
            )

        latest_number = (
            await db.execute(
                select(func.max(ManuscriptRevision.revision_number)).where(
                    ManuscriptRevision.project_id == project.id
                )
            )
        ).scalar_one()
        revision_id = uuid4()
        revision_number = int(latest_number or 0) + 1
        storage_key = (
            f"manuscripts/{current_user.id}/{project.id}/{revision_id}/original.docx"
        )
        await storage.upload_file(temp_path, storage_key, DOCX_MIME)

        revision = ManuscriptRevision(
            id=revision_id,
            project_id=project.id,
            user_id=current_user.id,
            revision_number=revision_number,
            supersedes_revision_id=project.active_revision_id,
            original_filename=filename,
            storage_key=storage_key,
            mime_type=DOCX_MIME,
            size_bytes=size_bytes,
            checksum=checksum,
            parser_version="phase1-2.0",
            status="queued",
        )
        db.add(revision)
        job = await enqueue_job(
            db,
            kind="ingest_manuscript",
            user_id=current_user.id,
            project_id=project.id,
            payload={
                "revision_id": str(revision.id),
                "project_id": str(project.id),
                "user_id": str(current_user.id),
                "apply_when_ready": apply_when_ready,
            },
        )
        db.add(
            Event(
                project_id=project.id,
                user_id=current_user.id,
                kind="manuscript_uploaded",
                data={
                    "revision_id": str(revision.id),
                    "revision_number": revision_number,
                    "filename": filename,
                    "size_bytes": size_bytes,
                    "checksum": checksum,
                },
            )
        )
        await db.commit()
        await db.refresh(revision)
        await db.refresh(job)
        return ManuscriptUploadResponse(
            revision=ManuscriptRevisionResponse.model_validate(revision),
            job_id=job.id,
            duplicate_of_revision_id=duplicate.id if duplicate else None,
        )
    except Exception:
        await db.rollback()
        if storage_key:
            try:
                await storage.delete(storage_key)
            except Exception:
                pass
        raise
    finally:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        await file.close()


@router.get(
    "/projects/{project_id}/revisions",
    response_model=list[ManuscriptRevisionResponse],
)
async def list_revisions(
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[ManuscriptRevision]:
    await fetch_owned_project(db, project_id, current_user.id)
    return list(
        (
            await db.execute(
                select(ManuscriptRevision)
                .where(
                    ManuscriptRevision.project_id == project_id,
                    ManuscriptRevision.user_id == current_user.id,
                )
                .order_by(ManuscriptRevision.revision_number.desc())
                .limit(limit)
                .offset(offset)
            )
        ).scalars()
    )


@router.get(
    "/projects/{project_id}/revisions/{revision_id}",
    response_model=ManuscriptRevisionResponse,
)
async def get_revision(
    project_id: UUID,
    revision_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> ManuscriptRevision:
    await fetch_owned_project(db, project_id, current_user.id)
    revision = (
        await db.execute(
            select(ManuscriptRevision).where(
                ManuscriptRevision.id == revision_id,
                ManuscriptRevision.project_id == project_id,
                ManuscriptRevision.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if revision is None:
        raise HTTPException(status_code=404, detail="Revision not found")
    return revision


@router.get("/revisions/{revision_id}/original", response_model=None)
async def download_original(
    revision_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    revision = (
        await db.execute(
            select(ManuscriptRevision).where(
                ManuscriptRevision.id == revision_id,
                ManuscriptRevision.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if revision is None:
        raise HTTPException(status_code=404, detail="Revision not found")
    storage = get_storage_service()
    url = await storage.presigned_download_url(
        revision.storage_key, revision.original_filename
    )
    if url:
        return RedirectResponse(url, status_code=307)
    return FileDownloadResponse(
        await storage.open_local_path(revision.storage_key),
        filename=revision.original_filename,
        media_type=revision.mime_type,
    )


@router.post(
    "/projects/{project_id}/revisions/{revision_id}/apply",
    response_model=ProjectDetailResponse,
)
async def restore_revision(
    project_id: UUID,
    revision_id: UUID,
    body: RevisionApplyRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    project = await fetch_owned_project(db, project_id, current_user.id)
    _assert_version(project, body.expected_version)
    revision = (
        await db.execute(
            select(ManuscriptRevision).where(
                ManuscriptRevision.id == revision_id,
                ManuscriptRevision.project_id == project.id,
                ManuscriptRevision.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if revision is None:
        raise HTTPException(status_code=404, detail="Revision not found")
    try:
        return await apply_revision(db, revision, project, current_user.id)
    except IngestionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@router.patch(
    "/projects/{project_id}/revisions/{revision_id}/issues/{issue_id}",
    response_model=ManuscriptRevisionResponse,
)
async def resolve_import_issue(
    project_id: UUID,
    revision_id: UUID,
    issue_id: str,
    body: IssueResolution,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    project = await fetch_owned_project(db, project_id, current_user.id)
    _assert_version(project, body.expected_version)
    revision = (
        await db.execute(
            select(ManuscriptRevision).where(
                ManuscriptRevision.id == revision_id,
                ManuscriptRevision.project_id == project.id,
                ManuscriptRevision.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if revision is None:
        raise HTTPException(status_code=404, detail="Revision not found")
    report = dict(revision.import_report or {})
    issues = [dict(issue) for issue in report.get("issues", [])]
    target = next((issue for issue in issues if issue.get("id") == issue_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="Import issue not found")
    target["status"] = "resolved"
    target["resolution"] = {
        "note": body.resolution,
        "resolved_by": str(current_user.id),
        "resolved_at": datetime.now(timezone.utc).isoformat(),
    }
    report["issues"] = issues
    report.setdefault("summary", {})["issues_open"] = sum(
        1 for issue in issues if issue.get("status") != "resolved"
    )
    report["summary"]["issues_blocking"] = sum(
        1
        for issue in issues
        if issue.get("status") != "resolved" and issue.get("severity") == "block"
    )
    revision.import_report = report
    project.document_version += 1
    db.add(
        Event(
            project_id=project.id,
            user_id=current_user.id,
            kind="import_issue_resolved",
            data={
                "revision_id": str(revision.id),
                "issue_id": issue_id,
                "document_version": project.document_version,
            },
        )
    )
    await db.commit()
    await db.refresh(revision)
    return revision


@router.get(
    "/projects/{project_id}/verify",
    response_model=VerificationResponse,
)
async def verify_readiness(
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> VerificationResponse:
    project = await fetch_owned_project(db, project_id, current_user.id)
    report = await verify_project(db, project)
    return VerificationResponse(
        document_version=project.document_version,
        manuscript_revision_id=project.active_revision_id,
        passed=report["pass"],
        report=report,
    )


@router.get("/projects/{project_id}/jobs", response_model=list[JobResponse])
async def list_project_jobs(
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    await fetch_owned_project(db, project_id, current_user.id)
    return list(
        (
            await db.execute(
                select(Job)
                .where(Job.project_id == project_id, Job.user_id == current_user.id)
                .order_by(Job.created_at.desc())
                .limit(50)
            )
        ).scalars()
    )


@router.patch(
    "/projects/{project_id}/sources/{source_id}", response_model=SourceResponse
)
async def update_source(
    project_id: UUID,
    source_id: UUID,
    body: SourceUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    project = await fetch_owned_project(db, project_id, current_user.id)
    source = (
        await db.execute(
            select(Source).where(
                Source.id == source_id,
                Source.project_id == project.id,
                Source.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    changes = body.model_dump(exclude_unset=True)
    verification_changed = any(
        key in changes for key in ("kind", "fields", "raw_entry", "identifiers")
    )
    for key, value in changes.items():
        setattr(source, key, value)
    if verification_changed and "verified" not in changes:
        source.verified = False
        source.verified_at = None
        source.verified_by = None
    if source.verified:
        source.verified_at = datetime.now(timezone.utc)
        source.verified_by = current_user.id
        source.verification_method = body.verification_method or "manual"
    else:
        source.verified_at = None
        source.verified_by = None
    project.document_version += 1
    await db.commit()
    await db.refresh(source)
    return source


@router.patch(
    "/projects/{project_id}/quotes/{quote_id}", response_model=dict
)
async def verify_quote(
    project_id: UUID,
    quote_id: UUID,
    body: QuoteVerificationUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    project = await fetch_owned_project(db, project_id, current_user.id)
    quote = (
        await db.execute(
            select(Quote).where(
                Quote.id == quote_id,
                Quote.project_id == project.id,
                Quote.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if quote is None:
        raise HTTPException(status_code=404, detail="Quotation not found")
    if body.expected_text is not None and body.expected_text != quote.text:
        raise HTTPException(
            status_code=409,
            detail="Quotation text changed since it was opened. Reload before verifying.",
        )
    quote.verified = body.verified
    quote.verification_method = body.verification_method
    quote.verified_at = datetime.now(timezone.utc) if body.verified else None
    quote.verified_by = current_user.id if body.verified else None
    project.document_version += 1
    await db.commit()
    return {
        "id": str(quote.id),
        "verified": quote.verified,
        "verified_at": quote.verified_at,
        "document_version": project.document_version,
    }
