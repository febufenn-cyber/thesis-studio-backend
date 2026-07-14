"""Markdown renderer — rendered directly from ThesisDocument (DESIGN §9).

Never derived from the DOCX output.
"""

from __future__ import annotations

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
from app.renderers.styles import get_citation_style
from app.renderers.works_cited import SourceLike


def _runs_md(runs: list[Run]) -> str:
    return "".join(f"*{r.text}*" if r.italic else r.text for r in runs)


def _block_md(block: Any) -> str:
    if isinstance(block, ParagraphBlock):
        return _runs_md(block.runs)
    if isinstance(block, BlockQuoteBlock):
        cite = f" ({block.citation})" if block.citation else ""
        return "> " + block.text.replace("\n", "\n> ") + cite
    if isinstance(block, VerseQuoteBlock):
        lines = "\n".join(f"> {line}" for line in block.lines)
        cite = f"\n> ({block.citation})" if block.citation else ""
        return lines + cite
    if isinstance(block, HeadingBlock):
        return ("###" if block.level == 2 else "####") + f" {block.text}"
    if isinstance(block, MarkerBlock):
        return f"**[{block.kind}: {block.note}]**"
    return ""


def render_md(
    doc: ThesisDocument,
    sources: dict[Any, SourceLike],
    profile: ResolvedProfile,
) -> str:
    """Render the canonical document to a Markdown string."""
    m = doc.meta
    out: list[str] = [f"# {m.title}", ""]
    meta_lines = [
        m.candidate.name + (f" (Reg. No. {m.candidate.reg_no})" if m.candidate.reg_no else ""),
        f"{m.department}, {m.college.name}",
        f"Affiliated to {m.college.affiliation}" if m.college.affiliation else "",
        f"Guide: {m.guide.name}" if m.guide.name else "",
        f"Submission: {m.submission.month} {m.submission.year or ''}".strip(),
    ]
    out += [line for line in meta_lines if line and not line.endswith(": ")]
    if m.ai_disclosure.enabled and m.ai_disclosure.text:
        out += ["", "## AI-Assistance Disclosure", "", m.ai_disclosure.text]

    for ch in doc.chapters:
        out += ["", f"## CHAPTER {_roman(ch.number)}: {ch.title.upper()}", ""]
        for block in ch.blocks:
            out += [_block_md(block), ""]

    used = [s for ref in doc.works_cited
            if (s := sources.get(ref.source_id) or sources.get(str(ref.source_id)))]
    if used:
        out += ["## WORKS CITED", ""]
        for entry in get_citation_style(doc.meta.citation_style).sorted_entries(used):
            out += [_runs_md(entry), ""]

    return "\n".join(out).rstrip() + "\n"
