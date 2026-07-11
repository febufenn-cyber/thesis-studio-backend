"""Deterministic manuscript structure detection → canonical ThesisDocument.

The parser classifies but never rewrites. Every generated block receives a
stable UUID plus the immutable manuscript revision and source paragraph index.
Ambiguities therefore remain addressable after later edits.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from uuid import UUID

from app.canonical.model import (
    Block,
    BlockQuoteBlock,
    ChapterDoc,
    FrontMatterEntry,
    HeadingBlock,
    ParagraphBlock,
    Run,
    ThesisDocument,
    ThesisMeta,
    VerseQuoteBlock,
)
from app.ingest.docx_extract import ExtractedPara


PARSER_VERSION = "phase1-2.0"

_ROMAN = {
    "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6,
    "VII": 7, "VIII": 8, "IX": 9, "X": 10, "XI": 11, "XII": 12,
}
_CHAPTER_RE = re.compile(r"^\s*CHAPTER\s+([IVX]+|\d+)\s*[:.\-–]?\s*(.*)$", re.IGNORECASE)
_WC_RE = re.compile(r"^\s*(WORKS\s+CITED|BIBLIOGRAPHY|REFERENCES)\s*$", re.IGNORECASE)
_FM_KINDS = {
    "CERTIFICATE": "certificate",
    "DECLARATION": "declaration",
    "ACKNOWLEDGEMENT": "acknowledgement",
    "ACKNOWLEDGEMENTS": "acknowledgement",
    "AI-ASSISTANCE DISCLOSURE": "ai_disclosure",
    "CONTENTS": "contents",
    "TABLE OF CONTENTS": "contents",
    "LIST OF ABBREVIATIONS": "abbreviations",
    "ABBREVIATIONS": "abbreviations",
}
_BLOCK_QUOTE_INDENT = 0.35
_CITE_TAIL_RE = re.compile(r"\(([^()]{1,80})\)\s*\.?\s*$")


@dataclass
class Ambiguity:
    chapter: int
    block_id: str
    block_index: int
    source_paragraph_index: int | None
    reason: str
    text_preview: str

    def as_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class ParseResult:
    document: ThesisDocument
    wc_raw_entries: list[tuple[int, list[Run]]] = field(default_factory=list)
    ambiguous: list[Ambiguity] = field(default_factory=list)
    parse_notes: list[str] = field(default_factory=list)


def _runs(p: ExtractedPara) -> list[Run]:
    return [Run(text=r.text, italic=r.italic) for r in p.runs]


def _identity(p: ExtractedPara, revision_id: UUID | None) -> dict:
    return {
        "source_revision_id": revision_id,
        "source_paragraph_index": p.index,
    }


def _paragraph(p: ExtractedPara, revision_id: UUID | None) -> ParagraphBlock:
    return ParagraphBlock(runs=_runs(p), **_identity(p, revision_id))


def _chapter_number(token: str) -> int:
    token = token.upper()
    return _ROMAN.get(token, 0) or (int(token) if token.isdigit() else 0)


def _split_citation(text: str) -> tuple[str, str]:
    m = _CITE_TAIL_RE.search(text)
    if not m:
        return text, ""
    return text[: m.start()].rstrip(), m.group(1).strip()


def _is_heading(p: ExtractedPara) -> int:
    t = p.text.strip()
    if len(t) > 90 or t.endswith((".", "?", "!", ",", ";", ":", "”", '"')):
        return 0
    if p.left_indent_in >= _BLOCK_QUOTE_INDENT or p.alignment == "center":
        return 0
    if p.mostly_bold:
        return 2
    nonempty = [r for r in p.runs if r.text.strip()]
    if nonempty and all(r.italic for r in nonempty):
        return 3
    return 0


def _classify_body_block(
    p: ExtractedPara,
    ch_no: int,
    blocks: list[Block],
    ambiguous: list[Ambiguity],
    revision_id: UUID | None,
) -> Block:
    text = p.text.strip()
    ident = _identity(p, revision_id)

    if p.left_indent_in >= _BLOCK_QUOTE_INDENT:
        lines = [ln for ln in text.split("\n") if ln.strip()]
        body, citation = _split_citation(text.replace("\n", " ").strip())
        if len(lines) >= 2 and all(len(ln.strip()) <= 65 for ln in lines):
            verse_lines, verse_citation = lines[:], ""
            m = _CITE_TAIL_RE.search(verse_lines[-1])
            if m:
                verse_citation = m.group(1).strip()
                verse_lines[-1] = verse_lines[-1][: m.start()].rstrip()
                if not verse_lines[-1]:
                    verse_lines.pop()
            block: Block = VerseQuoteBlock(lines=verse_lines, citation=verse_citation, **ident)
        else:
            block = BlockQuoteBlock(text=body, citation=citation, **ident)
        if not citation and isinstance(block, BlockQuoteBlock):
            ambiguous.append(
                Ambiguity(
                    chapter=ch_no,
                    block_id=str(block.id),
                    block_index=len(blocks),
                    source_paragraph_index=p.index,
                    reason="Indented block has no trailing citation: quotation or layout artifact?",
                    text_preview=text[:120],
                )
            )
        return block

    level = _is_heading(p)
    if level:
        return HeadingBlock(level=level, text=text, **ident)

    block = _paragraph(p, revision_id)
    # Short, styleless title-like lines are preserved as paragraphs but surfaced.
    if len(text) <= 80 and not text.endswith((".", "?", "!")) and p.style_name.lower() in {"normal", ""}:
        if text.istitle() and len(text.split()) <= 10:
            ambiguous.append(
                Ambiguity(
                    chapter=ch_no,
                    block_id=str(block.id),
                    block_index=len(blocks),
                    source_paragraph_index=p.index,
                    reason="Short title-like paragraph may be an unstyled section heading.",
                    text_preview=text[:120],
                )
            )
    return block


def parse_manuscript(
    paras: list[ExtractedPara], revision_id: UUID | None = None
) -> ParseResult:
    """Classify a paragraph stream into a revision-aware canonical document."""

    notes: list[str] = []
    ambiguous: list[Ambiguity] = []
    first_chapter = next(
        (i for i, p in enumerate(paras) if _CHAPTER_RE.match(p.text.strip())), None
    )
    wc_start = next(
        (i for i, p in enumerate(paras) if _WC_RE.match(p.text.strip())), None
    )
    if first_chapter is None:
        notes.append("No explicit CHAPTER boundary found; body was preserved as one chapter.")
    if wc_start is None:
        notes.append("No Works Cited/Bibliography heading was found.")

    front: list[FrontMatterEntry] = []
    fm_end = first_chapter if first_chapter is not None else 0
    current_kind: str | None = None
    current_blocks: list[Block] = []
    title_blocks: list[Block] = []

    def flush_fm() -> None:
        nonlocal current_kind, current_blocks
        if current_kind:
            front.append(FrontMatterEntry(kind=current_kind, body_blocks=current_blocks))
        current_kind, current_blocks = None, []

    for p in paras[:fm_end]:
        key = p.text.strip().upper().rstrip(":")
        if key in _FM_KINDS:
            flush_fm()
            current_kind = _FM_KINDS[key]
        elif current_kind:
            current_blocks.append(_paragraph(p, revision_id))
        else:
            title_blocks.append(_paragraph(p, revision_id))
    flush_fm()
    if title_blocks:
        front.insert(0, FrontMatterEntry(kind="title_page", body_blocks=title_blocks))
        notes.append("Original title-page paragraphs were preserved for metadata confirmation.")

    chapters: list[ChapterDoc] = []
    body_end = wc_start if wc_start is not None else len(paras)
    i = first_chapter if first_chapter is not None else 0
    current: ChapterDoc | None = None
    pending_title = False
    auto_no = 0

    while i < body_end:
        p = paras[i]
        match = _CHAPTER_RE.match(p.text.strip())
        if match:
            if current:
                chapters.append(current)
            auto_no += 1
            number = _chapter_number(match.group(1)) or auto_no
            inline_title = match.group(2).strip()
            current = ChapterDoc(number=number, title=inline_title, blocks=[])
            pending_title = not inline_title
        elif current is None:
            auto_no += 1
            current = ChapterDoc(number=auto_no, title="", blocks=[])
            pending_title = True
            continue
        elif pending_title and (p.all_caps or p.alignment == "center") and len(p.text) < 90:
            current.title = p.text.strip()
            pending_title = False
        else:
            pending_title = False
            current.blocks.append(
                _classify_body_block(p, current.number, current.blocks, ambiguous, revision_id)
            )
        i += 1
    if current:
        chapters.append(current)

    wc_raw: list[tuple[int, list[Run]]] = []
    if wc_start is not None:
        for p in paras[wc_start + 1 :]:
            if _CHAPTER_RE.match(p.text.strip()):
                break
            wc_raw.append((p.index, _runs(p)))

    document = ThesisDocument(
        meta=ThesisMeta(),
        front_matter=front,
        chapters=chapters,
        works_cited=[],
    )
    return ParseResult(
        document=document,
        wc_raw_entries=wc_raw,
        ambiguous=ambiguous,
        parse_notes=notes,
    )
