"""CITATION_VERIFIER — deterministic pre-export audit (blocking).

Implements the checks PROMPTS.md assigns to the verifier stage as pure code:
consistency between the document, the in-text citations, the registry, and
the Works Cited refs is mechanically checkable, so no model call is needed.
Severity 'block' prevents export; 'warn' is listed on the export screen.
Output matches the VerifierReport schema exactly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.canonical.model import (
    BlockQuoteBlock,
    MarkerBlock,
    ThesisDocument,
    VerseQuoteBlock,
)
from app.ingest.citations import VERIFY, InTextCitation, scan_document


@dataclass
class Violation:
    rule: str
    location: dict[str, Any]
    found: str
    expected: str
    severity: str  # "block" | "warn"


@dataclass
class VerifierReport:
    passed: bool
    violations: list[Violation] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "pass": self.passed,
            "violations": [v.__dict__ for v in self.violations],
            "counts": self.counts,
        }


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower().strip('"“”')


def _source_surname(fields: dict) -> str:
    author = str(fields.get("author", "")).strip()
    if author and author != VERIFY:
        return author.split(",")[0].strip().lower()
    title = str(fields.get("title", "")).strip()
    return title.split()[0].lower() if title else ""


def verify(
    doc: ThesisDocument,
    sources: dict[UUID, Any],   # id -> obj with .kind/.fields/.verified/.consulted_flag
    quotes: dict[UUID, Any],    # id -> obj with .text/.verified
) -> VerifierReport:
    """Audit the assembled document against the registry. Verifies, never fixes."""
    v: list[Violation] = []

    cited_refs = {r.source_id for r in doc.works_cited}
    surname_to_ids: dict[str, list[UUID]] = {}
    for sid, s in sources.items():
        surname_to_ids.setdefault(_source_surname(s.fields), []).append(sid)

    # 1. Works Cited refs must resolve; fields must be VERIFY-free.
    for ref in doc.works_cited:
        s = sources.get(ref.source_id)
        if s is None:
            v.append(Violation(
                rule="wc_ref_unknown_source", location={"chapter": 0, "block_index": 0},
                found=str(ref.source_id), expected="a registry source id",
                severity="block",
            ))
            continue
        bad = [k for k, val in s.fields.items() if VERIFY in str(val)]
        if bad:
            v.append(Violation(
                rule="wc_entry_verify_fields", location={"chapter": 0, "block_index": 0},
                found=f"{_source_surname(s.fields)}: {', '.join(bad)}",
                expected="complete bibliographic fields (never guessed)",
                severity="block",
            ))
        if not s.verified:
            v.append(Violation(
                rule="wc_source_unverified", location={"chapter": 0, "block_index": 0},
                found=_source_surname(s.fields) or str(ref.source_id),
                expected="operator/student confirms the source exists",
                severity="block",
            ))

    # 2. Quote blocks: quote_id present, verified, text matches registry.
    for ch in doc.chapters:
        for bi, block in enumerate(ch.blocks):
            loc = {"chapter": ch.number, "block_index": bi}
            if isinstance(block, (BlockQuoteBlock, VerseQuoteBlock)):
                if block.quote_id is None:
                    v.append(Violation(
                        rule="quote_missing_id", location=loc,
                        found=(block.text if isinstance(block, BlockQuoteBlock)
                               else " / ".join(block.lines))[:60],
                        expected="a quote_id from the verified registry",
                        severity="block",
                    ))
                    continue
                q = quotes.get(block.quote_id)
                if q is None or not getattr(q, "verified", False):
                    v.append(Violation(
                        rule="quote_unverified", location=loc,
                        found=str(block.quote_id),
                        expected="a verified registry quote",
                        severity="block",
                    ))
                    continue
                doc_text = (block.text if isinstance(block, BlockQuoteBlock)
                            else " ".join(block.lines))
                if _norm(doc_text) != _norm(q.text):
                    v.append(Violation(
                        rule="quote_text_divergence", location=loc,
                        found=doc_text[:80], expected=str(q.text)[:80],
                        severity="block",
                    ))
            elif isinstance(block, MarkerBlock):
                v.append(Violation(
                    rule="unresolved_marker", location=loc,
                    found=f"[{block.kind}: {block.note}]",
                    expected="marker resolved before export",
                    severity="block",
                ))

    # 3. In-text citations resolve to registry sources present in Works Cited.
    intext: list[InTextCitation] = scan_document(doc)
    used_ids: set[UUID] = set()
    for c in intext:
        ids = surname_to_ids.get(c.surname.lower(), [])
        loc = {"chapter": c.chapter, "block_index": c.block_index}
        if not ids:
            v.append(Violation(
                rule="citation_without_source", location=loc,
                found=c.raw, expected="a registry source with this surname",
                severity="block",
            ))
            continue
        used_ids.update(ids)
        missing_wc = [i for i in ids if i not in cited_refs]
        if len(missing_wc) == len(ids):
            v.append(Violation(
                rule="cited_source_missing_from_wc", location=loc,
                found=c.raw, expected="source listed in Works Cited",
                severity="block",
            ))
        if c.qtd_in:
            v.append(Violation(
                rule="qtd_in_usage", location=loc,
                found=c.raw, expected="attempt the original source",
                severity="warn",
            ))

    # 4. WC entries never cited and not consulted-flagged.
    for ref in doc.works_cited:
        s = sources.get(ref.source_id)
        if s is None:
            continue
        if ref.source_id not in used_ids and not getattr(s, "consulted_flag", False):
            v.append(Violation(
                rule="wc_entry_uncited", location={"chapter": 0, "block_index": 0},
                found=_source_surname(s.fields) or str(ref.source_id),
                expected="cited in text or flagged as consulted",
                severity="warn",
            ))

    counts = {
        "block": sum(1 for x in v if x.severity == "block"),
        "warn": sum(1 for x in v if x.severity == "warn"),
    }
    return VerifierReport(passed=counts["block"] == 0, violations=v, counts=counts)
