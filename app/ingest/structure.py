"""Deterministic manuscript structure detection → canonical ThesisDocument.

The parser classifies but never rewrites. Every generated block and structural
boundary receives stable identity plus immutable manuscript provenance.
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
    structural_paragraph_indexes: list[int] = field(default_factory=list)


def _runs(p: ExtractedPara) -> list[Run]:
    return [Run(text=r.text, italic=r.italic) for r in p.runs]


def _identity(p: ExtractedPara, revision_id: UUID | None) -> dict:
    return {"source_revision_id": revision_id, "source_paragraph_index": p.index}


def _paragraph(p: ExtractedPara, revision_id: UUID | None) -> ParagraphBlock:
    return ParagraphBlock(runs=_runs(p), **_identity(p, revision_id))


def _chapter_number(token: str) -> int:
    token = token.upper()
    return _ROMAN.get(token, 0) or (int(token) if token.isdigit() else 0)


def _split_citation(text: str) -> tuple[str, str]:
    match = _CITE_TAIL_RE.search(text)
    if not match:
        return text, ""
    return text[: match.start()].rstrip(), match.group(1).strip()


def _is_heading(p: ExtractedPara) -> int:
    text = p.text.strip()
    if len(text) > 90 or text.endswith((".", "?", "!", ",", ";", ":", "”", '"')):
        return 0
    if p.left_indent_in >= _BLOCK_QUOTE_INDENT or p.alignment == "center":
        return 0
    if p.mostly_bold:
        return 2
    nonempty = [run for run in p.runs if run.text.strip()]
    if nonempty and all(run.italic for run in nonempty):
        return 3
    return 0


def _classify_body_block(
    p: ExtractedPara,
    chapter_number: int,
    blocks: list[Block],
    ambiguities: list[Ambiguity],
    revision_id: UUID | None,
) -> Block:
    text = p.text.strip()
    identity = _identity(p, revision_id)

    if p.left_indent_in >= _BLOCK_QUOTE_INDENT:
        lines = [line for line in text.split("\n") if line.strip()]
        body, citation = _split_citation(text.replace("\n", " ").strip())
        if len(lines) >= 2 and all(len(line.strip()) <= 65 for line in lines):
            verse_lines, verse_citation = lines[:], ""
            match = _CITE_TAIL_RE.search(verse_lines[-1])
            if match:
                verse_citation = match.group(1).strip()
                verse_lines[-1] = verse_lines[-1][: match.start()].rstrip()
                if not verse_lines[-1]:
                    verse_lines.pop()
            block: Block = VerseQuoteBlock(
                lines=verse_lines, citation=verse_citation, **identity
            )
        else:
            block = BlockQuoteBlock(text=body, citation=citation, **identity)
        if not citation and isinstance(block, BlockQuoteBlock):
            ambiguities.append(
                Ambiguity(
                    chapter=chapter_number,
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
        return HeadingBlock(level=level, text=text, **identity)

    block = _paragraph(p, revision_id)
    if (
        len(text) <= 80
        and not text.endswith((".", "?", "!"))
        and p.style_name.lower() in {"normal", ""}
        and text.istitle()
        and len(text.split()) <= 10
    ):
        ambiguities.append(
            Ambiguity(
                chapter=chapter_number,
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
    ambiguities: list[Ambiguity] = []
    structural_indexes: list[int] = []
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
    current_heading_index: int | None = None
    title_blocks: list[Block] = []

    def flush_front_matter() -> None:
        nonlocal current_kind, current_blocks, current_heading_index
        if current_kind:
            front.append(
                FrontMatterEntry(
                    kind=current_kind,
                    body_blocks=current_blocks,
                    source_revision_id=revision_id,
                    source_paragraph_index=current_heading_index,
                )
            )
        current_kind, current_blocks, current_heading_index = None, [], None

    for para in paras[:fm_end]:
        key = para.text.strip().upper().rstrip(":")
        if key in _FM_KINDS:
            flush_front_matter()
            current_kind = _FM_KINDS[key]
            current_heading_index = para.index
            structural_indexes.append(para.index)
        elif current_kind:
            current_blocks.append(_paragraph(para, revision_id))
        else:
            title_blocks.append(_paragraph(para, revision_id))
    flush_front_matter()
    if title_blocks:
        first_index = title_blocks[0].source_paragraph_index
        front.insert(
            0,
            FrontMatterEntry(
                kind="title_page",
                body_blocks=title_blocks,
                source_revision_id=revision_id,
                source_paragraph_index=first_index,
            ),
        )
        notes.append("Original title-page paragraphs were preserved for metadata confirmation.")

    chapters: list[ChapterDoc] = []
    body_end = wc_start if wc_start is not None else len(paras)
    i = first_chapter if first_chapter is not None else 0
    current: ChapterDoc | None = None
    pending_title = False
    auto_number = 0

    while i < body_end:
        para = paras[i]
        match = _CHAPTER_RE.match(para.text.strip())
        if match:
            if current:
                chapters.append(current)
            auto_number += 1
            number = _chapter_number(match.group(1)) or auto_number
            inline_title = match.group(2).strip()
            current = ChapterDoc(
                number=number,
                title=inline_title,
                blocks=[],
                source_revision_id=revision_id,
                source_paragraph_index=para.index,
                title_source_paragraph_index=para.index if inline_title else None,
            )
            structural_indexes.append(para.index)
            pending_title = not inline_title
        elif current is None:
            auto_number += 1
            current = ChapterDoc(
                number=auto_number,
                title="",
                blocks=[],
                source_revision_id=revision_id,
            )
            pending_title = True
            continue
        elif pending_title and (para.all_caps or para.alignment == "center") and len(para.text) < 90:
            current.title = para.text.strip()
            current.title_source_paragraph_index = para.index
            structural_indexes.append(para.index)
            pending_title = False
        else:
            pending_title = False
            current.blocks.append(
                _classify_body_block(
                    para, current.number, current.blocks, ambiguities, revision_id
                )
            )
        i += 1
    if current:
        chapters.append(current)

    wc_raw: list[tuple[int, list[Run]]] = []
    if wc_start is not None:
        structural_indexes.append(paras[wc_start].index)
        for para in paras[wc_start + 1 :]:
            if _CHAPTER_RE.match(para.text.strip()):
                break
            wc_raw.append((para.index, _runs(para)))

    document = ThesisDocument(
        meta=ThesisMeta(), front_matter=front, chapters=chapters, works_cited=[]
    )
    return ParseResult(
        document=document,
        wc_raw_entries=wc_raw,
        ambiguous=ambiguities,
        parse_notes=notes,
        structural_paragraph_indexes=structural_indexes,
    )
