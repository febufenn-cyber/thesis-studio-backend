"""Export service — background jobs rendering a project to docx/pdf/md/txt.

Mirrors the v1 compile_service discipline: the background task opens its own
DB session, re-verifies ownership, sanitizes user-visible errors, and always
cleans up temp files.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import shutil
import tempfile
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.canonical.model import ThesisDocument
from app.db.session import AsyncSessionLocal
from app.models.export import Export
from app.models.project import Project
from app.models.source import Source
from app.models.style_profile import StyleProfile
from app.renderers.docx_renderer import RenderError, render_docx
from app.renderers.md_renderer import render_md
from app.renderers.pdf_renderer import (
    PdfConversionError,
    SofficeUnavailableError,
    convert_to_pdf,
)
from app.renderers.profiles import ResolvedProfile, resolve_profile
from app.renderers.txt_renderer import render_txt
from app.renderers.works_cited import MissingCitationField
from app.services.storage_service import get_storage_service


log = logging.getLogger(__name__)

EXPORT_FORMATS = ("docx", "pdf", "md", "txt")

MEDIA_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
    "md": "text/markdown",
    "txt": "text/plain",
}


def build_thesis_document(project: Project) -> ThesisDocument:
    """Validate the project's JSONB columns through the canonical model."""
    return ThesisDocument.model_validate(
        {
            "meta": project.meta or {},
            "front_matter": project.front_matter or [],
            "chapters": project.chapters or [],
            "works_cited": project.works_cited or [],
        }
    )


def _user_facing_error(exc: Exception) -> str:
    """Sanitized error stored on the Export row (visible to the owner)."""
    if isinstance(exc, SofficeUnavailableError):
        return str(exc)
    if isinstance(exc, PdfConversionError):
        return "PDF conversion failed. Please try again or export DOCX."
    if isinstance(exc, (RenderError, MissingCitationField)):
        return f"Document cannot be rendered: {exc}"[:500]
    if isinstance(exc, (KeyError, ValueError, TypeError)):
        return "The project document failed validation. Check meta/chapters JSON."
    return "Export failed unexpectedly. Please try again."


async def _resolve_project_profile(
    db: AsyncSession, project: Project
) -> ResolvedProfile:
    """Base format profile merged with the project's StyleProfile, if any."""
    override = None
    if project.style_profile_id:
        row = (
            await db.execute(
                select(StyleProfile).where(StyleProfile.id == project.style_profile_id)
            )
        ).scalar_one_or_none()
        override = row.data if row else None
    return resolve_profile(project.format_profile, override)


async def run_export(export_id: UUID, project_id: UUID, user_id: UUID) -> None:
    """Background export job for one Export row (one format)."""
    tmp_dir: str | None = None
    export_row: Export | None = None

    async with AsyncSessionLocal() as db:
        try:
            export_row = (
                await db.execute(select(Export).where(Export.id == export_id))
            ).scalar_one_or_none()
            if export_row is None:
                log.error("run_export: Export %s not found", export_id)
                return

            project = (
                await db.execute(select(Project).where(Project.id == project_id))
            ).scalar_one_or_none()
            if project is None or project.user_id != user_id:
                export_row.status = "failed"
                export_row.error_message = "Project not found or user mismatch"
                await db.commit()
                return

            doc = build_thesis_document(project)
            profile = await _resolve_project_profile(db, project)

            source_rows = (
                (await db.execute(
                    select(Source).where(Source.project_id == project_id)
                )).scalars().all()
            )
            sources = {s.id: s for s in source_rows}

            fmt = export_row.format
            tmp_dir = tempfile.mkdtemp(prefix="export_")
            out_path = os.path.join(tmp_dir, f"{export_id}.{fmt}")

            if fmt == "docx":
                await asyncio.to_thread(render_docx, doc, sources, profile, out_path)
            elif fmt == "pdf":
                docx_path = os.path.join(tmp_dir, f"{export_id}.docx")
                await asyncio.to_thread(render_docx, doc, sources, profile, docx_path)
                pdf_path = await asyncio.to_thread(convert_to_pdf, docx_path, tmp_dir)
                out_path = pdf_path
            elif fmt == "md":
                content = render_md(doc, sources, profile)
                await asyncio.to_thread(_write_text, out_path, content)
            elif fmt == "txt":
                content = render_txt(doc, sources, profile)
                await asyncio.to_thread(_write_text, out_path, content)
            else:
                raise ValueError(f"unknown export format {fmt!r}")

            key = f"exports/{user_id}/{project_id}/{export_id}.{fmt}"
            storage = get_storage_service()
            size = await storage.upload_file(
                out_path, key, content_type=MEDIA_TYPES.get(fmt, "application/octet-stream")
            )
            checksum = await asyncio.to_thread(_sha256, out_path)

            export_row.storage_key = key
            export_row.size_bytes = size
            export_row.checksum = checksum
            export_row.status = "ready"
            await db.commit()
            log.info("run_export: ready id=%s fmt=%s size=%d", export_id, fmt, size)

        except Exception as exc:
            log.exception("run_export: failed id=%s", export_id)
            if export_row is not None:
                try:
                    await db.rollback()
                    export_row.status = "failed"
                    export_row.error_message = _user_facing_error(exc)
                    await db.commit()
                except Exception:
                    log.exception("run_export: could not mark %s failed", export_id)
        finally:
            if tmp_dir:
                shutil.rmtree(tmp_dir, ignore_errors=True)


def _write_text(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()
