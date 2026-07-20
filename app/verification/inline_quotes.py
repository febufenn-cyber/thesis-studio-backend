"""Inline run-in quotation extraction (eval-governed).

MLA prose quotations live inside paragraphs — "..." (Surname 123) — not only
in indented blocks. This module finds them and links each to the registry
source its parenthetical citation resolves to. Never-guess rules:

- A quote links ONLY when the block's citation resolves unambiguously
  (resolve_citation: unique surname, or surname + title hint). Two same-author
  sources with a bare surname citation = correctly skipped, never guessed.
- Quoted spans shorter than _MIN_CHARS are skipped (sentence fragments and
  scare quotes are noise, not evidence).

Quality is governed by tests/quote_corpus.py — frozen, append-only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.canonical.model import ParagraphBlock, ThesisDocument

_MIN_CHARS = 20
_MAX_CHARS = 600

# Straight and curly double quotes; span kept verbatim.
_INLINE_QUOTE_RE = re.compile(r"[“\"](?P<t>[^”\"]+)[”\"]")


@dataclass
class InlineQuote:
    block_id: str
    chapter: int
    source_id: str
    text: str
    pages: str
    raw_citation: str


def extract_inline_quotes(
    document: ThesisDocument,
    citation_by_block: dict[str, dict],
) -> list[InlineQuote]:
    """Quotes from paragraphs whose parenthetical citation RESOLVED to a source.

    ``citation_by_block`` is the ingest scan result: block_id -> the citation
    dict (with resolved_source_id / pages / raw) produced by scan_document +
    resolve_citation.
    """
    found: list[InlineQuote] = []
    for chapter in document.chapters:
        for block in chapter.blocks:
            if not isinstance(block, ParagraphBlock):
                continue
            citation = citation_by_block.get(str(block.id))
            if not citation or not citation.get("resolved_source_id"):
                continue
            text = "".join(run.text for run in block.runs)
            for match in _INLINE_QUOTE_RE.finditer(text):
                span = match.group("t").strip()
                if not (_MIN_CHARS <= len(span) <= _MAX_CHARS):
                    continue
                found.append(
                    InlineQuote(
                        block_id=str(block.id),
                        chapter=chapter.number,
                        source_id=str(citation["resolved_source_id"]),
                        text=span,
                        pages=str(citation.get("pages", "") or ""),
                        raw_citation=str(citation.get("raw", "") or ""),
                    )
                )
    return found
