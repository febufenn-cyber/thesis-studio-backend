"""Deterministic academic-integrity verifier.

The verifier never fixes content. Heuristic matching is used only when no
human decision exists for the exact stable block and raw citation occurrence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.canonical.model import BlockQuoteBlock, MarkerBlock, ThesisDocument, VerseQuoteBlock
from app.ingest.citations import VERIFY, InTextCitation, resolve_citation, scan_document


@dataclass
class Violation:
    rule: str
    location: dict[str, Any]
    found: str
    expected: str
    severity: str


@dataclass
class VerifierReport:
    passed: bool
    violations: list[Violation] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "pass": self.passed,
            "violations": [violation.__dict__ for violation in self.violations],
            "counts": self.counts,
        }


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower().strip('"“”')


def _source_label(fields: dict) -> str:
    author = str(fields.get("author", "")).strip()
    if author and author != VERIFY:
        return author.split(",")[0].strip()
    title = str(fields.get("title", "")).strip()
    return title or "unknown source"


def verify(
    doc: ThesisDocument,
    sources: dict[UUID, Any],
    quotes: dict[UUID, Any],
    resolutions: dict[tuple[str, str], UUID] | None = None,
) -> VerifierReport:
    violations: list[Violation] = []
    cited_refs = {ref.source_id for ref in doc.works_cited}
    human_resolutions = resolutions or {}

    for ref in doc.works_cited:
        source = sources.get(ref.source_id)
        location = {"section": "works_cited", "source_id": str(ref.source_id)}
        if source is None:
            violations.append(
                Violation(
                    "wc_ref_unknown_source",
                    location,
                    str(ref.source_id),
                    "a registry source id",
                    "block",
                )
            )
            continue
        invalid_fields = [
            key
            for key, value in source.fields.items()
            if not str(value).strip() or VERIFY in str(value)
        ]
        if invalid_fields:
            violations.append(
                Violation(
                    "wc_entry_verify_fields",
                    location,
                    f"{_source_label(source.fields)}: {', '.join(invalid_fields)}",
                    "complete bibliographic fields confirmed against the source",
                    "block",
                )
            )
        if getattr(source, "parse_status", "") == "preserved_raw":
            violations.append(
                Violation(
                    "wc_raw_entry_requires_confirmation",
                    location,
                    getattr(source, "raw_entry", "") or _source_label(source.fields),
                    "operator confirms the preserved raw entry before final export",
                    "block",
                )
            )
        if not source.verified:
            violations.append(
                Violation(
                    "wc_source_unverified",
                    location,
                    _source_label(source.fields),
                    "operator/student confirms that the source and fields are accurate",
                    "block",
                )
            )

    for chapter in doc.chapters:
        for block_index, block in enumerate(chapter.blocks):
            location = {
                "chapter": chapter.number,
                "chapter_id": str(chapter.id),
                "block_id": str(block.id),
                "block_index": block_index,
            }
            if isinstance(block, (BlockQuoteBlock, VerseQuoteBlock)):
                if block.quote_id is None:
                    violations.append(
                        Violation(
                            "quote_missing_id",
                            location,
                            (
                                block.text
                                if isinstance(block, BlockQuoteBlock)
                                else " / ".join(block.lines)
                            )[:80],
                            "a quotation record linked to one source",
                            "block",
                        )
                    )
                    continue
                quote = quotes.get(block.quote_id)
                if quote is None or not getattr(quote, "verified", False):
                    violations.append(
                        Violation(
                            "quote_unverified",
                            location,
                            str(block.quote_id),
                            "a human-verified registry quotation",
                            "block",
                        )
                    )
                    continue
                document_text = (
                    block.text
                    if isinstance(block, BlockQuoteBlock)
                    else "\n".join(block.lines)
                )
                if _normalise(document_text) != _normalise(quote.text):
                    violations.append(
                        Violation(
                            "quote_text_divergence",
                            location,
                            document_text[:100],
                            str(quote.text)[:100],
                            "block",
                        )
                    )
            elif isinstance(block, MarkerBlock):
                violations.append(
                    Violation(
                        "unresolved_marker",
                        location,
                        f"[{block.kind}: {block.note}]",
                        "marker resolved before final export",
                        "block",
                    )
                )

    in_text: list[InTextCitation] = scan_document(doc)
    used_ids: set[UUID] = set()
    for citation in in_text:
        key = (citation.block_id, citation.raw)
        human_source_id = human_resolutions.get(key)
        if human_source_id is not None:
            resolved_id = human_source_id if human_source_id in sources else None
            candidates: list[UUID] = [human_source_id]
            reason = "human_resolution" if resolved_id else "human_resolution_source_missing"
        else:
            resolved_id, candidates, reason = resolve_citation(citation, sources)
        location = {
            "chapter": citation.chapter,
            "block_id": citation.block_id,
            "block_index": citation.block_index,
            "resolution": reason,
        }
        if resolved_id is None:
            rule = "citation_ambiguous_source" if candidates else "citation_without_source"
            violations.append(
                Violation(
                    rule,
                    location,
                    citation.raw,
                    (
                        "operator selects one source from: "
                        + ", ".join(str(value) for value in candidates)
                        if candidates
                        else "a matching registry source"
                    ),
                    "block",
                )
            )
            continue
        used_ids.add(resolved_id)
        if resolved_id not in cited_refs:
            violations.append(
                Violation(
                    "cited_source_missing_from_wc",
                    location,
                    citation.raw,
                    "resolved source appears in Works Cited",
                    "block",
                )
            )
        if citation.qtd_in:
            violations.append(
                Violation(
                    "qtd_in_usage",
                    location,
                    citation.raw,
                    "consult the original source where feasible",
                    "warn",
                )
            )

    for ref in doc.works_cited:
        source = sources.get(ref.source_id)
        if source is None:
            continue
        if ref.source_id not in used_ids and not getattr(source, "consulted_flag", False):
            violations.append(
                Violation(
                    "wc_entry_uncited",
                    {"section": "works_cited", "source_id": str(ref.source_id)},
                    _source_label(source.fields),
                    "source cited in the thesis or marked as Works Consulted",
                    "warn",
                )
            )

    counts = {
        "block": sum(1 for violation in violations if violation.severity == "block"),
        "warn": sum(1 for violation in violations if violation.severity == "warn"),
    }
    return VerifierReport(
        passed=counts["block"] == 0,
        violations=violations,
        counts=counts,
    )
