"""Submission Pack — the single deliverable (one click, one zip).

Bundles everything a student hands to their institution: the rendered thesis
PDF, the integrity report, the AI-use statement, the quote-verification report
and the provenance log, plus a manifest with per-file SHA-256 checksums, the
document version, and an honest review/final state.

Honesty rules: a pack built while verification findings are open is a REVIEW
pack — the PDF keeps its loud [UNVERIFIED — ...] markers (render strict=False)
and the manifest says so; nothing is ever marked verified by packing. A FINAL
pack renders strict, so an incomplete citation can never ship unmarked.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import tempfile
import zipfile
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.project import Project
from app.models.source import Source
from app.renderers.docx_renderer import render_docx
from app.renderers.pdf_renderer import convert_to_pdf
from app.services.export_service import _resolve_project_profile, build_thesis_document
from app.services.integrity_report import build_integrity_report
from app.services.provenance_service import (
    generate_ai_use_statement,
    get_provenance_timeline,
)
from app.services.quote_verification_service import verification_report
from app.services.verification_service import verify_project


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def build_submission_pack(db: AsyncSession, project: Project, user_id) -> tuple[bytes, dict]:
    """Assemble the pack; returns (zip bytes, manifest dict)."""
    settings = get_settings()
    verification = await verify_project(db, project)
    state = "final" if verification.get("pass") else "review"

    # 1 · The thesis PDF (review packs keep UNVERIFIED markers; final is strict).
    document = build_thesis_document(project)
    rows = list(
        (await db.execute(select(Source).where(Source.project_id == project.id))).scalars()
    )
    sources = {row.id: row for row in rows}
    profile, profile_version = await _resolve_project_profile(db, project)

    def _render() -> bytes:
        with tempfile.TemporaryDirectory(prefix="pack_") as tmp:
            docx_path = os.path.join(tmp, "thesis.docx")
            render_docx(document, sources, profile, docx_path, strict=(state == "final"))
            pdf_path = convert_to_pdf(docx_path, tmp)
            with open(pdf_path, "rb") as fh:
                return fh.read()

    pdf_bytes = await asyncio.to_thread(_render)

    # 2 · Integrity report.
    integrity = await build_integrity_report(db, project)

    # 3 · AI-use statement (default institutional template).
    statement = await generate_ai_use_statement(db, project, generated_by=user_id)
    statement_doc = {
        "template_key": statement.template_key,
        "document_version": statement.document_version,
        "document_checksum": statement.document_checksum,
        "content_hash": statement.content_hash,
        "body_text": statement.body_text,
        "rollup": statement.rollup,
    }

    # 4 · Quote-verification report (advisory; never a verified bit).
    quote_rows = await verification_report(db, project.id)
    quotes_doc = {
        "advisory": True,
        "results": [
            {
                "quote_id": str(r.quote_id),
                "kind": r.kind,
                "status": r.status,
                "score": r.score,
                "method": r.method,
                "matched_locator": r.matched_locator,
                "checked_at": r.checked_at.isoformat() if r.checked_at else None,
            }
            for r in quote_rows
        ],
    }

    # 5 · Provenance log (accepted-proposal authorship transitions).
    provenance = await get_provenance_timeline(db, project)

    files: dict[str, bytes] = {
        "thesis.pdf": pdf_bytes,
        "integrity_report.json": json.dumps(integrity, indent=1, default=str).encode(),
        "ai_use_statement.json": json.dumps(statement_doc, indent=1, default=str).encode(),
        "ai_use_statement.txt": statement.body_text.encode(),
        "quote_verification.json": json.dumps(quotes_doc, indent=1, default=str).encode(),
        "provenance_log.json": json.dumps(provenance, indent=1, default=str).encode(),
    }

    manifest = {
        "pack": "acadensia-submission-pack",
        "version": 1,
        "state": state,  # review packs carry visible UNVERIFIED markers
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project_id": str(project.id),
        "project_title": project.title,
        "document_version": project.document_version,
        "format_profile": project.format_profile,
        "profile_version": profile_version,
        "schema_version": settings.SCHEMA_VERSION,
        "renderer_version": settings.RENDERER_VERSION,
        "verification": {
            "pass": bool(verification.get("pass")),
            "counts": verification.get("counts", {}),
        },
        "files": {name: {"sha256": _sha256(data), "bytes": len(data)} for name, data in files.items()},
        "note": (
            "Checksums attest file integrity, not truth: verification proves "
            "internal traceability, never universal validity."
        ),
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
        zf.writestr("manifest.json", json.dumps(manifest, indent=1, default=str))
    return buf.getvalue(), manifest
