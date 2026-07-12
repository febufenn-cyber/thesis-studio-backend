"""Authoritative PDF preview creation using the real document renderer."""

from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import tempfile
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.document_preview import DocumentPreview
from app.models.project import Project
from app.models.source import Source
from app.renderers.docx_renderer import render_docx
from app.renderers.pdf_renderer import convert_to_pdf
from app.services.export_service import _resolve_project_profile, build_thesis_document
from app.services.job_queue import enqueue_job
from app.services.registry_scope import active_revision_rows
from app.services.storage_service import get_storage_service


class StalePreviewError(RuntimeError):
    pass


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _profile_digest(profile_version: str) -> str:
    return hashlib.sha256(profile_version.encode("utf-8")).hexdigest()[:16]


def _page_count(path: str) -> int | None:
    with open(path, "rb") as handle:
        data = handle.read()
    count = data.count(b"/Type /Page") - data.count(b"/Type /Pages")
    return count if count > 0 else None


async def request_preview(
    db: AsyncSession,
    project: Project,
    user_id: UUID,
    *,
    expected_version: int,
    force: bool = False,
) -> DocumentPreview:
    if project.document_version != expected_version:
        raise StalePreviewError("Project changed in another session. Reload before previewing.")
    _profile, profile_version = await _resolve_project_profile(db, project)
    row = (
        await db.execute(
            select(DocumentPreview).where(
                DocumentPreview.project_id == project.id,
                DocumentPreview.document_version == project.document_version,
                DocumentPreview.profile_version == profile_version,
            )
        )
    ).scalar_one_or_none()
    if row and not force and row.status in {"queued", "running", "ready"}:
        return row
    if row is None:
        row = DocumentPreview(
            project_id=project.id,
            user_id=user_id,
            manuscript_revision_id=project.active_revision_id,
            document_version=project.document_version,
            profile_version=profile_version,
            status="queued",
            manifest={
                "state": "authoritative_preview",
                "document_version": project.document_version,
                "profile_version": profile_version,
            },
        )
        db.add(row)
        await db.flush()
    else:
        row.status = "queued"
        row.error_message = None
        row.storage_key = None
        row.checksum = None
        row.size_bytes = None
        row.page_count = None
    await enqueue_job(
        db,
        kind="preview",
        user_id=user_id,
        project_id=project.id,
        payload={
            "preview_id": str(row.id),
            "project_id": str(project.id),
            "user_id": str(user_id),
        },
        max_attempts=1,
    )
    await db.commit()
    await db.refresh(row)
    return row


async def run_preview(preview_id: UUID, project_id: UUID, user_id: UUID) -> None:
    temp_dir: str | None = None
    async with AsyncSessionLocal() as db:
        preview = (
            await db.execute(select(DocumentPreview).where(DocumentPreview.id == preview_id))
        ).scalar_one_or_none()
        if preview is None:
            raise ValueError("Preview row no longer exists.")
        preview.status = "running"
        preview.error_message = None
        await db.commit()
        try:
            project = (
                await db.execute(
                    select(Project).where(Project.id == project_id, Project.user_id == user_id)
                )
            ).scalar_one_or_none()
            if project is None:
                raise ValueError("Project no longer exists.")
            if project.document_version != preview.document_version:
                raise StalePreviewError("Document changed before preview rendering started.")
            if project.active_revision_id != preview.manuscript_revision_id:
                raise StalePreviewError("Active manuscript revision changed before preview rendering.")

            document = build_thesis_document(project)
            profile, profile_version = await _resolve_project_profile(db, project)
            if profile_version != preview.profile_version:
                raise StalePreviewError("Format profile changed before preview rendering.")
            all_sources = list(
                (await db.execute(select(Source).where(Source.project_id == project.id))).scalars()
            )
            source_rows = active_revision_rows(all_sources, project.active_revision_id)
            sources = {source.id: source for source in source_rows}

            temp_dir = tempfile.mkdtemp(prefix="preview_")
            docx_path = os.path.join(temp_dir, f"{preview.id}.docx")
            await asyncio.to_thread(render_docx, document, sources, profile, docx_path)
            pdf_path = await asyncio.to_thread(convert_to_pdf, docx_path, temp_dir)
            with open(pdf_path, "rb") as handle:
                if handle.read(5) != b"%PDF-":
                    raise RuntimeError("Preview conversion did not produce a valid PDF.")

            checksum = await asyncio.to_thread(_sha256, pdf_path)
            key = (
                f"previews/{user_id}/{project.id}/"
                f"v{preview.document_version}-{_profile_digest(profile_version)}.pdf"
            )
            storage = get_storage_service()
            size = await storage.upload_file(pdf_path, key, content_type="application/pdf")
            pages = await asyncio.to_thread(_page_count, pdf_path)
            manifest = dict(preview.manifest or {})
            manifest.update(
                {
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "document_version": preview.document_version,
                    "manuscript_revision_id": (
                        str(preview.manuscript_revision_id)
                        if preview.manuscript_revision_id
                        else None
                    ),
                    "profile_version": preview.profile_version,
                    "output_checksum_sha256": checksum,
                    "page_count": pages,
                    "authoritative": True,
                    "warning": (
                        "This preview uses the final renderer. Unresolved markers may remain visible "
                        "until review is complete."
                    ),
                }
            )
            preview.storage_key = key
            preview.checksum = checksum
            preview.size_bytes = size
            preview.page_count = pages
            preview.manifest = manifest
            preview.status = "ready"
            await db.commit()
        except Exception as exc:
            await db.rollback()
            row = (
                await db.execute(select(DocumentPreview).where(DocumentPreview.id == preview_id))
            ).scalar_one_or_none()
            if row:
                row.status = "failed"
                row.error_message = str(exc)[:500]
                await db.commit()
            raise
        finally:
            if temp_dir:
                shutil.rmtree(temp_dir, ignore_errors=True)
