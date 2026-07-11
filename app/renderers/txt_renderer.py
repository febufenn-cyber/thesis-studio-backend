"""Plain-text renderer — rendered directly from ThesisDocument (DESIGN §9)."""

from __future__ import annotations

import textwrap
from typing import Any

from app.canonical.model import (
    BlockQuoteBlock,
    HeadingBlock,
    MarkerBlock,
    ParagraphBlock,
    Run,
    ThesisDocument,
    VerseQuoteBlock,
)
from app.renderers.docx_renderer import _roman
from app.renderers.profiles import ResolvedProfile
from app.renderers.works_cited import SourceLike, sorted_entries

_WIDTH = 80


def _runs_txt(runs: list[Run]) -> str:
    return "".join(r.text for r in runs)


def _wrap(text: str, indent: str = "") -> str:
    return textwrap.fill(
        text, width=_WIDTH, initial_indent=indent, subsequent_indent=indent
    )


def _block_txt(block: Any) -> str:
    if isinstance(block, ParagraphBlock):
        return _wrap(_runs_txt(block.runs))
    if isinstance(block, BlockQuoteBlock):
        cite = f" ({block.citation})" if block.citation else ""
        return _wrap(block.text + cite, indent="    ")
    if isinstance(block, VerseQuoteBlock):
        lines = "\n".join(f"    {line}" for line in block.lines)
        cite = f"\n    ({block.citation})" if block.citation else ""
        return lines + cite
    if isinstance(block, HeadingBlock):
        return block.text.upper() if block.level == 2 else block.text
    if isinstance(block, MarkerBlock):
        return f"[{block.kind}: {block.note}]"
    return ""


def render_txt(
    doc: ThesisDocument,
    sources: dict[Any, SourceLike],
    profile: ResolvedProfile,
) -> str:
    """Render the canonical document to a plain-text string (80 columns)."""
    m = doc.meta
    out: list[str] = [m.title.upper(), "=" * min(len(m.title), _WIDTH), ""]
    for line in (
        m.candidate.name,
        f"{m.department}, {m.college.name}",
        f"Submission: {m.submission.month} {m.submission.year or ''}".strip(),
    ):
        if line.strip():
            out.append(line)

    for ch in doc.chapters:
        header = f"CHAPTER {_roman(ch.number)} — {ch.title.upper()}"
        out += ["", "", header, "-" * min(len(header), _WIDTH), ""]
        for block in ch.blocks:
            out += [_block_txt(block), ""]

    used = [s for ref in doc.works_cited
            if (s := sources.get(ref.source_id) or sources.get(str(ref.source_id)))]
    if used:
        out += ["", "WORKS CITED", "-----------", ""]
        for entry in sorted_entries(used):
            text = _runs_txt(entry)
            out.append(textwrap.fill(text, width=_WIDTH, subsequent_indent="    "))

    return "\n".join(out).rstrip() + "\n"
