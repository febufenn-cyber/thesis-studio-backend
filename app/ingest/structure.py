"""Deterministic manuscript structure detection → canonical ThesisDocument.

Maps an ExtractedPara stream onto the canonical model (MANUSCRIPT_PARSER's
contract, DESIGN.md/PROMPTS.md): classify and structure, never rewrite. Text
is preserved byte-for-byte inside blocks. Ambiguous regions become normal
paragraphs but are reported in ParseResult.ambiguous for operator review —
the canonical model has no 'unclassified' block, so review targets are
surfaced by (chapter, block_index) instead of by a special type.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

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

_ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7,
          "VIII": 8, "IX": 9, "X": 10, "XI": 11, "XII": 12}

_CHAPTER_RE = re.compile(
    r"^\s*CHAPTER\s+([IVX]+|\d+)\s*[:.\-–]?\s*(.*)$", re.IGNORECASE
)
_WC_RE = re.compile(
    r"^\s*(WORKS\s+CITED|BIBLIOGRAPHY|REFERENCES)\s*$", re.IGNORECASE
)
# Front-matter page headings → canonical FrontMatterEntry kinds.
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

_BLOCK_QUOTE_INDENT = 0.35  # inches; MLA block quotes indent 0.5", tolerate less
_CITE_TAIL_RE = re.compile(r"\(([^()]{1,80})\)\s*\.?\s*$")


@dataclass
class Ambiguity:
    chapter: int          # 0 = front matter
    block_index: int
    reason: str
    text_preview: str


@dataclass
class ParseResult:
    document: ThesisDocument
    wc_raw_entries: list[list[Run]] = field(default_factory=list)
    ambiguous: list[Ambiguity] = field(default_factory=list)
    parse_notes: list[str] = field(default_factory=list)


def _runs(p: ExtractedPara) -> list[Run]:
    return [Run(text=r.text, italic=r.italic) for r in p.runs]


def _chapter_number(token: str) -> int:
    token = token.upper()
    return _ROMAN.get(token, 0) or (int(token) if token.isdigit() else 0)


def _split_citation(text: str) -> tuple[str, str]:
    """Split a trailing parenthetical citation off quote text (MLA §5)."""
    m = _CITE_TAIL_RE.search(text)
    if not m:
        return text, ""
    body = text[: m.start()].rstrip()
    return body, m.group(1).strip()


def _is_heading(p: ExtractedPara) -> int:
    """0 = not a heading; 2/3 = heading level."""
    t = p.text.strip()
    if len(t) > 90 or t.endswith((".", "?", "!", ",", ";", ":", "”", '"')):
        return 0
    if p.left_indent_in >= _BLOCK_QUOTE_INDENT or p.alignment == "center":
        return 0
    if p.mostly_bold:
        return 2
    if all(r.italic for r in p.runs if r.text.strip()):
        return 3
    return 0


def _classify_body_block(
    p: ExtractedPara, ch_no: int, blocks: list[Block], ambiguous: list[Ambiguity]
) -> Block:
    """One body paragraph → one canonical block."""
    text = p.text.strip()

    if p.left_indent_in >= _BLOCK_QUOTE_INDENT:
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        body, citation = _split_citation(text.replace("\n", " ").strip())
        # Verse: multiple short lines with preserved lineation.
        if len(lines) >= 2 and all(len(ln) <= 65 for ln in lines):
            vbody, vcite = lines[:], ""
            m = _CITE_TAIL_RE.search(vbody[-1])
            if m:
                vcite = m.group(1).strip()
                vbody[-1] = vbody[-1][: m.start()].rstrip()
                if not vbody[-1]:
                    vbody.pop()
            return VerseQuoteBlock(lines=vbody, citation=vcite)
        if not citation:
            ambiguous.append(Ambiguity(
                chapter=ch_no, block_index=len(blocks),
                reason="indented block without trailing citation — block quote or layout artifact?",
                text_preview=text[:80],
            ))
        return BlockQuoteBlock(text=body, citation=citation)

    level = _is_heading(p)
    if level:
        return HeadingBlock(level=level, text=text)

    return ParagraphBlock(runs=_runs(p))


def parse_manuscript(paras: list[ExtractedPara]) -> ParseResult:
    """Classify a paragraph stream into a canonical ThesisDocument.

    Returns the document plus raw Works Cited entries (for citations.py) and
    the ambiguity report. Front matter meta fields are left for the operator
    (title page text lands in parse_notes, not guessed into meta).
    """
    notes: list[str] = []
    ambiguous: list[Ambiguity] = []

    # --- Pass 1: find section boundaries ---------------------------------
    first_chapter = next(
        (i for i, p in enumerate(paras) if _CHAPTER_RE.match(p.text.strip())), None
    )
    wc_start = next(
        (i for i, p in enumerate(paras) if _WC_RE.match(p.text.strip())), None
    )
    if first_chapter is None:
        notes.append("No 'CHAPTER <n>' boundary found — whole body treated as one chapter.")
    if wc_start is None:
        notes.append("No Works Cited/Bibliography heading found.")

    # --- Front matter -----------------------------------------------------
    front: list[FrontMatterEntry] = []
    fm_end = first_chapter if first_chapter is not None else 0
    i = 0
    current_kind: str | None = None
    current_blocks: list[Block] = []
    title_page_seen = False

    def flush_fm() -> None:
        nonlocal current_kind, current_blocks
        if current_kind:
            front.append(FrontMatterEntry(kind=current_kind, body_blocks=current_blocks))
        current_kind, current_blocks = None, []

    while i < fm_end:
        p = paras[i]
        key = p.text.strip().upper().rstrip(":")
        if key in _FM_KINDS:
            flush_fm()
            current_kind = _FM_KINDS[key]
        elif current_kind:
            current_blocks.append(ParagraphBlock(runs=_runs(p)))
        else:
            if not title_page_seen:
                title_page_seen = True
                front.insert(0, FrontMatterEntry(kind="title_page"))
                notes.append("Title-page text captured in notes; fill meta from it: "
                             + " / ".join(q.text.strip() for q in paras[:min(fm_end, 12)])[:400])
        i += 1
    flush_fm()

    # --- Chapters ----------------------------------------------------------
    chapters: list[ChapterDoc] = []
    body_end = wc_start if wc_start is not None else len(paras)
    i = first_chapter if first_chapter is not None else 0

    current: ChapterDoc | None = None
    pending_title: bool = False
    auto_no = 0

    while i < body_end:
        p = paras[i]
        m = _CHAPTER_RE.match(p.text.strip())
        if m:
            if current:
                chapters.append(current)
            auto_no += 1
            no = _chapter_number(m.group(1)) or auto_no
            inline_title = m.group(2).strip()
            current = ChapterDoc(number=no, title=inline_title, blocks=[])
            pending_title = not inline_title
        elif current is None:
            auto_no += 1
            current = ChapterDoc(number=auto_no, title="", blocks=[])
            pending_title = True
            continue  # reclassify this paragraph inside the new chapter
        elif pending_title and (p.all_caps or p.alignment == "center") and len(p.text) < 90:
            current.title = p.text.strip()
            pending_title = False
        else:
            pending_title = False
            current.blocks.append(
                _classify_body_block(p, current.number, current.blocks, ambiguous)
            )
        i += 1
    if current:
        chapters.append(current)

    # --- Works Cited (raw entries; citations.py structures them) ----------
    wc_raw: list[list[Run]] = []
    if wc_start is not None:
        for p in paras[wc_start + 1:]:
            if _CHAPTER_RE.match(p.text.strip()):
                break
            wc_raw.append(_runs(p))

    doc = ThesisDocument(
        meta=ThesisMeta(),
        front_matter=front,
        chapters=chapters,
        works_cited=[],  # filled after registry candidates get IDs
    )
    return ParseResult(document=doc, wc_raw_entries=wc_raw,
                       ambiguous=ambiguous, parse_notes=notes)
