"""Immutable manuscript ingestion and revision application.

A revision is parsed entirely in memory before canonical document, registry
sources, quotations and the import report are committed together. The original
object in storage is never overwritten.
"""

from __future__ import annotations

import asyncio
import re
import logging
import os
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid5, NAMESPACE_URL

from sqlalchemy import select, update

from app.canonical.model import (
    BlockQuoteBlock,
    ParagraphBlock,
    ThesisDocument,
    ThesisMeta,
    VerseQuoteBlock,
    WorksCitedRef,
)
from app.db.session import AsyncSessionLocal
from app.ingest.citations import parse_wc_entries, resolve_citation, scan_document
from app.ingest.docx_extract import extract_paragraphs
from app.ingest.preflight import inspect_docx
from app.ingest.structure import PARSER_VERSION, parse_manuscript
from app.models.event import Event
from app.models.manuscript_revision import ManuscriptRevision
from app.models.project import Project
from app.models.quote import Quote
from app.models.source import Source
from app.renderers.source_types import source_type_for_kind
from app.services.storage_service import get_storage_service


log = logging.getLogger(__name__)


class IngestionError(RuntimeError):
    """The manuscript could not be converted safely."""


def _issue_id(revision_id: UUID, category: str, key: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"robofox:{revision_id}:{category}:{key}"))


def _iter_blocks(document: ThesisDocument):
    for entry in document.front_matter:
        for block in entry.body_blocks:
            yield 0, block
    for chapter in document.chapters:
        for block in chapter.blocks:
            yield chapter.number, block


def _accounted_indexes(document: ThesisDocument, parse_result: Any, candidates: list[Any]) -> set[int]:
    indexes = set(parse_result.structural_paragraph_indexes)
    for entry in document.front_matter:
        if entry.source_paragraph_index is not None:
            indexes.add(entry.source_paragraph_index)
        for block in entry.body_blocks:
            if block.source_paragraph_index is not None:
                indexes.add(block.source_paragraph_index)
    for chapter in document.chapters:
        for index in (
            chapter.source_paragraph_index,
            chapter.title_source_paragraph_index,
        ):
            if index is not None:
                indexes.add(index)
        for block in chapter.blocks:
            if block.source_paragraph_index is not None:
                indexes.add(block.source_paragraph_index)
    for candidate in candidates:
        if candidate.source_paragraph_index is not None:
            indexes.add(candidate.source_paragraph_index)
    return indexes


def _build_report(
    revision: ManuscriptRevision,
    preflight: Any,
    paras: list[Any],
    parse_result: Any,
    candidates: list[Any],
    citation_results: list[dict],
    quotation_results: list[dict],
) -> dict:
    issues: list[dict] = []
    for preflight_issue in preflight.issues:
        issues.append(
            {
                "id": _issue_id(revision.id, "preflight", preflight_issue.code),
                **preflight_issue.as_dict(),
                "status": "open",
                "resolution": None,
            }
        )
    for ambiguity in parse_result.ambiguous:
        issues.append(
            {
                "id": _issue_id(revision.id, "ambiguity", ambiguity.block_id),
                "code": "structure_ambiguity",
                "severity": "review",
                "count": 1,
                "message": ambiguity.reason,
                "evidence": ambiguity.as_dict(),
                "status": "open",
                "resolution": None,
            }
        )
    for result in citation_results:
        if result["status"] != "resolved":
            issues.append(
                {
                    "id": _issue_id(
                        revision.id,
                        "citation",
                        f"{result['block_id']}:{result['raw']}",
                    ),
                    "code": "citation_resolution_required",
                    "severity": "block",
                    "count": 1,
                    "message": "Citation could not be linked unambiguously to one registry source.",
                    "evidence": result,
                    "status": "open",
                    "resolution": None,
                }
            )
    for result in quotation_results:
        if result["status"] != "linked_unverified":
            issues.append(
                {
                    "id": _issue_id(revision.id, "quotation", result["block_id"]),
                    "code": "quotation_source_required",
                    "severity": "block",
                    "count": 1,
                    "message": "Quotation requires an unambiguous source before verification.",
                    "evidence": result,
                    "status": "open",
                    "resolution": None,
                }
            )

    accounted = _accounted_indexes(parse_result.document, parse_result, candidates)
    source_indexes = {p.index for p in paras if p.text.strip()}
    missing_indexes = sorted(source_indexes - accounted)
    if missing_indexes:
        issues.append(
            {
                "id": _issue_id(revision.id, "preservation", "unaccounted"),
                "code": "unaccounted_source_paragraphs",
                "severity": "block",
                "count": len(missing_indexes),
                "message": "One or more non-empty source paragraphs were not mapped to canonical content or registry entries.",
                "evidence": {"paragraph_indexes": missing_indexes[:200]},
                "status": "open",
                "resolution": None,
            }
        )

    source_chars = sum(len(p.text) for p in paras if p.text.strip())
    accounted_chars = sum(len(p.text) for p in paras if p.index in accounted)
    source_count = len(source_indexes)
    return {
        "schema_version": 1,
        "revision_id": str(revision.id),
        "parser_version": PARSER_VERSION,
        "summary": {
            "chapters": len(parse_result.document.chapters),
            "front_matter_sections": len(parse_result.document.front_matter),
            "works_cited_entries": len(candidates),
            "in_text_citations": len(citation_results),
            "quotation_blocks": len(quotation_results),
            "issues_open": len(issues),
            "issues_blocking": sum(1 for issue in issues if issue["severity"] == "block"),
        },
        "preflight": preflight.as_dict(),
        "parse_notes": parse_result.parse_notes,
        "citations": citation_results,
        "quotations": quotation_results,
        "preservation": {
            "source_nonempty_paragraphs": source_count,
            "accounted_paragraphs": len(source_indexes & accounted),
            "unaccounted_paragraphs": missing_indexes,
            "source_characters": source_chars,
            "accounted_characters": accounted_chars,
            "paragraph_coverage": round(
                len(source_indexes & accounted) / max(source_count, 1), 4
            ),
        },
        "issues": issues,
    }


async def ingest_revision(
    revision_id: UUID,
    project_id: UUID,
    user_id: UUID,
    *,
    apply_when_ready: bool = True,
) -> None:
    """Parse and atomically persist one immutable manuscript revision."""

    storage = get_storage_service()
    local_path: str | None = None
    async with AsyncSessionLocal() as db:
        revision = (
            await db.execute(
                select(ManuscriptRevision).where(
                    ManuscriptRevision.id == revision_id,
                    ManuscriptRevision.project_id == project_id,
                    ManuscriptRevision.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        project = (
            await db.execute(
                select(Project).where(Project.id == project_id, Project.user_id == user_id)
            )
        ).scalar_one_or_none()
        if revision is None or project is None:
            raise IngestionError("Revision or project no longer exists.")

        revision.status = "processing"
        revision.error_message = None
        await db.commit()

        try:
            local_path = await storage.download_to_temp(revision.storage_key)
            # These are CPU/IO-bound and synchronous: inspect_docx streams the
            # whole file through ClamAV over a socket, and extract/parse run
            # python-docx. Run them off the event loop so one upload cannot stall
            # every other request for the scan+parse duration.
            preflight = await asyncio.to_thread(inspect_docx, local_path)
            paragraphs = await asyncio.to_thread(extract_paragraphs, local_path)
            parse_result = await asyncio.to_thread(parse_manuscript, paragraphs, revision.id)
            document = parse_result.document
            document.meta = ThesisMeta.model_validate(project.meta or {})
            candidates = parse_wc_entries(parse_result.wc_raw_entries)

            source_rows: list[Source] = []
            for candidate in candidates:
                source = Source(
                    project_id=project.id,
                    user_id=user_id,
                    kind=candidate.kind,
                    source_type=source_type_for_kind(candidate.kind),
                    fields=candidate.fields,
                    raw_entry=candidate.raw_entry,
                    parse_status=candidate.parse_status,
                    source_paragraph_index=candidate.source_paragraph_index,
                    import_revision_id=revision.id,
                    parser_confidence=candidate.parser_confidence,
                    parser_version=PARSER_VERSION,
                    identifiers=candidate.identifiers,
                    verified=False,
                    verify_note=candidate.verify_note,
                )
                db.add(source)
                source_rows.append(source)
            await db.flush()
            source_map = {source.id: source for source in source_rows}
            document.works_cited = [WorksCitedRef(source_id=s.id) for s in source_rows]

            citation_results: list[dict] = []
            citations = scan_document(document)
            for citation in citations:
                resolved_id, candidates_ids, reason = resolve_citation(citation, source_map)
                citation_results.append(
                    {
                        "raw": citation.raw,
                        "chapter": citation.chapter,
                        "block_id": citation.block_id,
                        "block_index": citation.block_index,
                        "title_hint": citation.title_hint,
                        "pages": citation.pages,
                        "status": "resolved" if resolved_id else "unresolved",
                        "resolved_source_id": str(resolved_id) if resolved_id else None,
                        "candidate_source_ids": [str(value) for value in candidates_ids],
                        "reason": reason,
                    }
                )

            citation_by_block = {
                result["block_id"]: result for result in citation_results
            }
            quotation_results: list[dict] = []
            for chapter_number, block in _iter_blocks(document):
                if not isinstance(block, (BlockQuoteBlock, VerseQuoteBlock)):
                    continue
                citation_result = citation_by_block.get(str(block.id))
                resolved_source_id = (
                    UUID(citation_result["resolved_source_id"])
                    if citation_result and citation_result["resolved_source_id"]
                    else None
                )
                if resolved_source_id is None:
                    quotation_results.append(
                        {
                            "block_id": str(block.id),
                            "chapter": chapter_number,
                            "citation": block.citation,
                            "status": "source_unresolved",
                        }
                    )
                    continue
                quote_text = (
                    block.text
                    if isinstance(block, BlockQuoteBlock)
                    else "\n".join(block.lines)
                )
                quote = Quote(
                    source_id=resolved_source_id,
                    project_id=project.id,
                    user_id=user_id,
                    page_or_loc=(citation_result or {}).get("pages", ""),
                    text=quote_text,
                    method="extracted",
                    import_revision_id=revision.id,
                    source_paragraph_index=block.source_paragraph_index,
                    evidence_snapshot={
                        "raw_citation": block.citation,
                        "block_id": str(block.id),
                        "revision_id": str(revision.id),
                    },
                    verified=False,
                )
                db.add(quote)
                await db.flush()
                block.quote_id = quote.id
                quotation_results.append(
                    {
                        "block_id": str(block.id),
                        "chapter": chapter_number,
                        "citation": block.citation,
                        "source_id": str(resolved_source_id),
                        "quote_id": str(quote.id),
                        "status": "linked_unverified",
                    }
                )

            # Inline run-in quotations (FRICTION_LOG F6; eval-governed in
            # tests/quote_corpus.py). Linked only via unambiguous citations.
            from app.verification.inline_quotes import extract_inline_quotes

            for iq in extract_inline_quotes(document, citation_by_block):
                quote = Quote(
                    source_id=UUID(iq.source_id),
                    project_id=project.id,
                    user_id=user_id,
                    page_or_loc=iq.pages,
                    text=iq.text,
                    method="extracted",
                    import_revision_id=revision.id,
                    source_paragraph_index=None,
                    evidence_snapshot={
                        "raw_citation": iq.raw_citation,
                        "block_id": iq.block_id,
                        "revision_id": str(revision.id),
                        "inline": True,
                    },
                    verified=False,
                )
                db.add(quote)
                await db.flush()
                quotation_results.append(
                    {
                        "block_id": iq.block_id,
                        "chapter": iq.chapter,
                        "citation": iq.raw_citation,
                        "source_id": iq.source_id,
                        "quote_id": str(quote.id),
                        "status": "linked_unverified",
                    }
                )

            report = _build_report(
                revision,
                preflight,
                paragraphs,
                parse_result,
                candidates,
                citation_results,
                quotation_results,
            )
            snapshot = document.model_dump(mode="json")
            revision.canonical_snapshot = snapshot
            revision.import_report = report
            revision.status = "ready"

            if apply_when_ready:
                await db.execute(
                    update(ManuscriptRevision)
                    .where(
                        ManuscriptRevision.project_id == project.id,
                        ManuscriptRevision.id != revision.id,
                    )
                    .values(applied=False)
                )
                project.meta = snapshot["meta"]
                project.front_matter = snapshot["front_matter"]
                project.chapters = snapshot["chapters"]
                project.works_cited = snapshot["works_cited"]
                project.active_revision_id = revision.id
                project.document_version += 1
                revision.applied = True
                revision.applied_at = datetime.now(timezone.utc)

            db.add(
                Event(
                    project_id=project.id,
                    user_id=user_id,
                    kind="manuscript_ingested",
                    data={
                        "revision_id": str(revision.id),
                        "revision_number": revision.revision_number,
                        "checksum": revision.checksum,
                        "parser_version": PARSER_VERSION,
                        "applied": apply_when_ready,
                        "document_version": project.document_version,
                        "blocking_issues": report["summary"]["issues_blocking"],
                    },
                )
            )
            await db.commit()
            log.info(
                "ingestion ready project=%s revision=%s coverage=%s",
                project.id,
                revision.id,
                report["preservation"]["paragraph_coverage"],
            )
        except Exception as exc:
            log.exception("ingestion failed revision=%s", revision_id)
            await db.rollback()
            failed = (
                await db.execute(
                    select(ManuscriptRevision).where(ManuscriptRevision.id == revision_id)
                )
            ).scalar_one_or_none()
            if failed is not None:
                failed.status = "failed"
                failed.error_message = "The manuscript could not be imported safely."
                await db.commit()
            raise
        finally:
            if local_path:
                try:
                    os.unlink(local_path)
                except OSError:
                    pass


async def apply_revision(
    db: Any,
    revision: ManuscriptRevision,
    project: Project,
    user_id: UUID,
) -> Project:
    """Restore/apply a ready immutable revision to the canonical project."""

    if revision.status != "ready" or not revision.canonical_snapshot:
        raise IngestionError("Only a successfully parsed revision can be applied.")
    snapshot = ThesisDocument.model_validate(revision.canonical_snapshot).model_dump(mode="json")
    await db.execute(
        update(ManuscriptRevision)
        .where(
            ManuscriptRevision.project_id == project.id,
            ManuscriptRevision.id != revision.id,
        )
        .values(applied=False)
    )
    project.meta = snapshot["meta"]
    project.front_matter = snapshot["front_matter"]
    project.chapters = snapshot["chapters"]
    project.works_cited = snapshot["works_cited"]
    project.active_revision_id = revision.id
    project.document_version += 1
    revision.applied = True
    revision.applied_at = datetime.now(timezone.utc)
    db.add(
        Event(
            project_id=project.id,
            user_id=user_id,
            kind="manuscript_revision_applied",
            data={
                "revision_id": str(revision.id),
                "document_version": project.document_version,
            },
        )
    )
    await db.commit()
    await db.refresh(project)
    return project
