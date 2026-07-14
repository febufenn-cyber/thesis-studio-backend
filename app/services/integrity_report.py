"""Integrity Report — provenance, not detection (docs/LLD_MISSING_FEATURES.md MF4).

Aggregates what Acadensia already knows into one attestable summary bound to a
document checksum: AI-use provenance, quote-verification results, reference
resolution/retraction status, and unresolved markers. It ASSERTS provenance; it
runs no classifier and never claims "AI-generated" or "plagiarised". Absence of
evidence is reported honestly as unknown/unverifiable, never as clean.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collaboration.workflow import canonical_checksum
from app.models.project import Project
from app.models.source import Source
from app.provenance.rollup import build_rollup
from app.renderers.field_schema import missing_required
from app.services.export_service import build_thesis_document
from app.services.quote_verification_service import verification_report


async def _reference_section(db: AsyncSession, project: Project) -> dict:
    sources = list(
        (await db.execute(select(Source).where(Source.project_id == project.id))).scalars()
    )
    counts = {
        "total": len(sources),
        "resolved": 0,
        "unresolved": 0,
        "ambiguous": 0,
        "unattempted": 0,
        "verified": 0,
        "retracted": 0,
        "concern": 0,
        "verify_incomplete": 0,
    }
    for source in sources:
        status = source.resolution_status
        if status == "resolved":
            counts["resolved"] += 1
        elif status == "unresolved":
            counts["unresolved"] += 1
        elif status == "ambiguous":
            counts["ambiguous"] += 1
        else:
            counts["unattempted"] += 1

        if source.verified:
            counts["verified"] += 1
        if source.retraction_status == "retracted":
            counts["retracted"] += 1
        elif source.retraction_status == "concern":
            counts["concern"] += 1

        if missing_required(source.kind, source.fields or {}):
            counts["verify_incomplete"] += 1

    ready = counts["retracted"] == 0 and counts["verify_incomplete"] == 0
    return {"counts": counts, "ready": ready}


def _marker_section(project: Project) -> dict:
    document = build_thesis_document(project)
    kinds: dict[str, int] = {}
    total = 0
    for chapter in document.chapters:
        for block in chapter.blocks:
            if block.type == "marker":
                kind = getattr(block, "kind", "unknown")
                kinds[kind] = kinds.get(kind, 0) + 1
                total += 1
    for entry in document.front_matter:
        for block in entry.body_blocks:
            if block.type == "marker":
                kind = getattr(block, "kind", "unknown")
                kinds[kind] = kinds.get(kind, 0) + 1
                total += 1
    return {"total": total, "kinds": kinds, "ready": total == 0}


async def _quote_section(db: AsyncSession, project: Project) -> dict:
    rows = await verification_report(db, project.id)
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    # "ready" only when nothing is a failed/uncertain check; absence of checks is
    # not treated as clean — it is simply reported (checked == 0).
    ready = counts.get("drift", 0) == 0 and counts.get("not_found", 0) == 0
    return {"checked": len(rows), "counts": counts, "ready": ready}


async def build_integrity_report(db: AsyncSession, project: Project) -> dict:
    """Assemble the integrity report for a project (read-only aggregation)."""
    rollup = await build_rollup(db, project, document_version=project.document_version)
    references = await _reference_section(db, project)
    quotes = await _quote_section(db, project)
    markers = _marker_section(project)

    return {
        "project_id": str(project.id),
        "document_version": project.document_version,
        "document_checksum": canonical_checksum(project),
        "assertion": (
            "This report asserts provenance and verification signals recorded by "
            "Acadensia. It does not detect plagiarism or AI-generated text; absence "
            "of a signal is reported as unknown, never as clean."
        ),
        "ai_provenance": rollup.to_dict(),
        "references": references,
        "quote_verification": quotes,
        "open_markers": markers,
        "ready": references["ready"] and markers["ready"] and quotes["ready"],
    }
