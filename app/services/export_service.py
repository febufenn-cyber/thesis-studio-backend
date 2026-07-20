"""Durable export worker for DOCX/PDF/Markdown/Text artifacts."""

from __future__ import annotations

import asyncio
import functools
import hashlib
import logging
import os
import shutil
import tempfile
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.disclosure import ai_disclosure_summary
from app.canonical.model import ThesisDocument
from app.db.session import AsyncSessionLocal
from app.models.export import Export
from app.models.manuscript_revision import ManuscriptRevision
from app.models.project import Project
from app.models.quote import Quote
from app.models.source import Source
from app.models.style_profile import StyleProfile
from app.renderers.docx_renderer import RenderError, render_docx
from app.renderers.md_renderer import render_md
from app.renderers.pdf_renderer import PdfConversionError, SofficeUnavailableError, convert_to_pdf
from app.renderers.phase1_profiles import resolve_phase1_profile
from app.renderers.profiles import ResolvedProfile
from app.renderers.txt_renderer import render_txt
from app.renderers.works_cited import MissingCitationField
from app.services.registry_scope import active_revision_rows
from app.services.storage_service import get_storage_service
from app.services.verification_service import post_render_qa


log = logging.getLogger(__name__)
EXPORT_FORMATS = ("docx", "pdf", "md", "txt")
MEDIA_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
    "md": "text/markdown",
    "txt": "text/plain",
}


class StaleExportError(RuntimeError):
    """The project changed after this export was requested."""


def build_thesis_document(project: Project) -> ThesisDocument:
    return ThesisDocument.model_validate(
        {
            "meta": project.meta or {},
            "front_matter": project.front_matter or [],
            "chapters": project.chapters or [],
            "works_cited": project.works_cited or [],
        }
    )


def _user_facing_error(exc: Exception) -> str:
    if isinstance(exc, StaleExportError):
        return str(exc)
    if isinstance(exc, SofficeUnavailableError):
        return str(exc)
    if isinstance(exc, PdfConversionError):
        return "PDF conversion failed. DOCX remains available; check the PDF stack and retry."
    if isinstance(exc, (RenderError, MissingCitationField)):
        return f"Document cannot be rendered: {exc}"[:500]
    if isinstance(exc, (KeyError, ValueError, TypeError)):
        return "The project document failed canonical validation."
    return "Export failed unexpectedly. Please retry."


def _is_review_export(export_row: Export) -> bool:
    """Return whether this artifact is intentionally non-final."""

    manifest = export_row.manifest or {}
    if manifest.get("state") == "final":
        return False
    if manifest.get("state") == "review":
        return True
    return not bool((export_row.report or {}).get("pass"))


def _apply_review_qa_policy(post_qa: dict, review_export: bool) -> dict:
    """Allow visible unresolved markers only in clearly labelled review files."""

    if not review_export:
        return post_qa
    blocking: list[dict] = []
    for finding in post_qa.get("violations", []):
        if finding.get("rule") == "unresolved_marker_rendered":
            finding["severity"] = "warn"
            finding["expected"] = (
                "review exports may retain visible markers; resolve them before final export"
            )
        else:
            blocking.append(finding)
    post_qa["pass"] = not blocking
    post_qa["review_export"] = True
    return post_qa


async def _resolve_project_profile(
    db: AsyncSession, project: Project
) -> tuple[ResolvedProfile, str]:
    override = None
    style_version: str | None = None
    if project.style_profile_id:
        row = (
            await db.execute(
                select(StyleProfile).where(StyleProfile.id == project.style_profile_id)
            )
        ).scalar_one_or_none()
        if row:
            override = row.data
            style_version = f"style:{row.id}:{row.created_at.isoformat()}"
    profile, governed_version = resolve_phase1_profile(project.format_profile, override)
    return profile, style_version or governed_version


async def run_export(export_id: UUID, project_id: UUID, user_id: UUID) -> None:
    """Render one queued Export row and raise on failure so the job can retry."""

    temp_dir: str | None = None
    export_row: Export | None = None
    caught: Exception | None = None
    async with AsyncSessionLocal() as db:
        try:
            export_row = (
                await db.execute(select(Export).where(Export.id == export_id))
            ).scalar_one_or_none()
            if export_row is None:
                raise ValueError("Export row no longer exists")
            export_row.status = "running"
            export_row.error_message = None
            await db.commit()

            project = (
                await db.execute(select(Project).where(Project.id == project_id))
            ).scalar_one_or_none()
            if project is None or project.user_id != user_id:
                raise ValueError("Project not found or user mismatch")
            if project.document_version != export_row.document_version:
                raise StaleExportError(
                    "Project changed after export was queued; request a new export from the current version."
                )
            if project.active_revision_id != export_row.manuscript_revision_id:
                raise StaleExportError(
                    "The active manuscript revision changed after export was queued."
                )

            review_export = _is_review_export(export_row)
            document = build_thesis_document(project)
            profile, profile_version = await _resolve_project_profile(db, project)
            export_row.profile_version = profile_version
            all_sources = list(
                (
                    await db.execute(select(Source).where(Source.project_id == project_id))
                ).scalars()
            )
            all_quotes = list(
                (
                    await db.execute(select(Quote).where(Quote.project_id == project_id))
                ).scalars()
            )
            source_rows = active_revision_rows(all_sources, project.active_revision_id)
            quote_rows = active_revision_rows(all_quotes, project.active_revision_id)
            sources = {source.id: source for source in source_rows}
            revision = None
            if export_row.manuscript_revision_id:
                revision = (
                    await db.execute(
                        select(ManuscriptRevision).where(
                            ManuscriptRevision.id == export_row.manuscript_revision_id
                        )
                    )
                ).scalar_one_or_none()

            fmt = export_row.format
            temp_dir = tempfile.mkdtemp(prefix="export_")
            output_path = os.path.join(temp_dir, f"{export_id}.{fmt}")
            # Review exports render incomplete citations with loud [UNVERIFIED]
            # markers instead of refusing (strict=False); final exports keep the
            # hard refusal so a finished document can never launder a gap.
            strict_render = not review_export
            if fmt == "docx":
                await asyncio.to_thread(
                    functools.partial(render_docx, strict=strict_render),
                    document, sources, profile, output_path,
                )
            elif fmt == "pdf":
                docx_path = os.path.join(temp_dir, f"{export_id}.docx")
                await asyncio.to_thread(
                    functools.partial(render_docx, strict=strict_render),
                    document, sources, profile, docx_path,
                )
                output_path = await asyncio.to_thread(convert_to_pdf, docx_path, temp_dir)
            elif fmt == "md":
                await asyncio.to_thread(
                    _write_text, output_path, render_md(document, sources, profile)
                )
            elif fmt == "txt":
                await asyncio.to_thread(
                    _write_text, output_path, render_txt(document, sources, profile)
                )
            else:
                raise ValueError(f"Unknown export format {fmt!r}")

            post_qa = await asyncio.to_thread(
                post_render_qa, output_path, fmt, document, profile
            )
            post_qa = _apply_review_qa_policy(post_qa, review_export)
            if not post_qa["pass"]:
                raise RenderError(
                    "; ".join(
                        violation["rule"]
                        for violation in post_qa["violations"]
                        if violation.get("severity", "block") == "block"
                    )
                )

            checksum = await asyncio.to_thread(_sha256, output_path)
            key = f"exports/{user_id}/{project_id}/{export_id}.{fmt}"
            storage = get_storage_service()
            size = await storage.upload_file(
                output_path,
                key,
                content_type=MEDIA_TYPES.get(fmt, "application/octet-stream"),
            )

            report = dict(export_row.report or {})
            report["post_render"] = post_qa
            disclosure = await ai_disclosure_summary(
                db, project, document_version=export_row.document_version
            )
            report["ai_disclosure"] = disclosure
            manifest = dict(export_row.manifest or {})
            manifest.setdefault("state", "review" if review_export else "final")
            manifest.update(
                {
                    "export_id": str(export_row.id),
                    "export_format": fmt,
                    "exported_at": datetime.now(timezone.utc).isoformat(),
                    "output_checksum_sha256": checksum,
                    "output_size_bytes": size,
                    "document_version": export_row.document_version,
                    "manuscript_revision_id": (
                        str(export_row.manuscript_revision_id)
                        if export_row.manuscript_revision_id
                        else None
                    ),
                    "original_checksum_sha256": revision.checksum if revision else None,
                    "parser_version": revision.parser_version if revision else None,
                    "canonical_schema_version": (
                        revision.canonical_schema_version
                        if revision
                        else document.schema_version
                    ),
                    "format_profile_version": profile_version,
                    "sources_total": len(source_rows),
                    "sources_verified": sum(1 for source in source_rows if source.verified),
                    "quotations_total": len(quote_rows),
                    "quotations_verified": sum(1 for quote in quote_rows if quote.verified),
                    "verification_passed": bool(report.get("pass")),
                    "verification_counts": report.get("counts", {}),
                    "ai_involvement": disclosure,
                }
            )
            export_row.storage_key = key
            export_row.size_bytes = size
            export_row.checksum = checksum
            export_row.report = report
            export_row.manifest = manifest
            export_row.status = "ready"
            await db.commit()
            log.info(
                "export ready id=%s fmt=%s size=%d state=%s",
                export_id,
                fmt,
                size,
                manifest["state"],
            )
        except Exception as exc:
            caught = exc
            log.exception("export failed id=%s", export_id)
            if export_row is not None:
                try:
                    await db.rollback()
                    row = (
                        await db.execute(select(Export).where(Export.id == export_id))
                    ).scalar_one_or_none()
                    if row is not None:
                        row.status = "failed"
                        row.error_message = _user_facing_error(exc)
                        await db.commit()
                except Exception:
                    log.exception("could not mark export %s failed", export_id)
        finally:
            if temp_dir:
                shutil.rmtree(temp_dir, ignore_errors=True)

    if caught is not None:
        raise caught


def _write_text(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
