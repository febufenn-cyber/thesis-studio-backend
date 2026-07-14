"""LaTeX export — rendered directly from the canonical ThesisDocument.

Produces a self-contained, compilable ``article`` document with no package
dependencies. Like the other renderers this walks the ThesisDocument directly
(never derived from the DOCX output) and never invents bibliographic data: any
absent field is simply skipped. All author-supplied text is escaped so LaTeX
special characters in the manuscript can never break compilation.
"""

from __future__ import annotations

import re
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
from app.renderers.works_cited import SourceLike

_LATEX_SPECIALS = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def escape_latex(text: str) -> str:
    """Escape the LaTeX special characters ``& % $ # _ { } ~ ^ \\``."""
    if text is None:
        return ""
    return "".join(_LATEX_SPECIALS.get(ch, ch) for ch in str(text))


def _runs_latex(runs: list[Run]) -> str:
    parts: list[str] = []
    for r in runs or []:
        body = escape_latex(r.text)
        parts.append(f"\\textit{{{body}}}" if r.italic else body)
    return "".join(parts)


def _cite_key(fields: dict, used: dict[str, int]) -> str:
    author = str(fields.get("author", "")).strip()
    surname = author.split(",")[0].strip() if author else str(fields.get("title", "")).strip()
    surname = re.sub(r"[^A-Za-z0-9]", "", surname) or "ref"
    year = re.sub(r"[^0-9]", "", str(fields.get("year", ""))) or "nd"
    base = f"{surname}{year}"
    n = used.get(base, 0)
    used[base] = n + 1
    return base if n == 0 else f"{base}{chr(ord('a') + n - 1)}"


def _block_latex(block: Any) -> str:
    if isinstance(block, ParagraphBlock):
        return _runs_latex(block.runs)
    if isinstance(block, BlockQuoteBlock):
        body = escape_latex(block.text)
        if block.citation:
            body += f" ({escape_latex(block.citation)})"
        return f"\\begin{{quote}}\n{body}\n\\end{{quote}}"
    if isinstance(block, VerseQuoteBlock):
        lines = " \\\\\n".join(escape_latex(line) for line in (block.lines or []))
        if block.citation:
            lines += f" \\\\\n({escape_latex(block.citation)})"
        return f"\\begin{{verse}}\n{lines}\n\\end{{verse}}"
    if isinstance(block, HeadingBlock):
        cmd = "subsection" if block.level == 2 else "subsubsection"
        return f"\\{cmd}{{{escape_latex(block.text)}}}"
    if isinstance(block, MarkerBlock):
        note = escape_latex(block.note).replace("\n", " ")
        return f"% TODO [{escape_latex(block.kind)}]: {note}"
    return ""


def _bibliography(doc: ThesisDocument, sources: dict[Any, SourceLike]) -> list[str]:
    resolved: list[SourceLike] = []
    for ref in doc.works_cited:
        src = sources.get(ref.source_id) or sources.get(str(ref.source_id))
        if src is not None:
            resolved.append(src)
    if not resolved:
        return []

    used: dict[str, int] = {}
    out = ["\\begin{thebibliography}{99}"]
    for src in resolved:
        fields = getattr(src, "fields", {}) or {}
        key = _cite_key(fields, used)
        pieces: list[str] = []
        author = str(fields.get("author", "")).strip()
        title = str(fields.get("title", "")).strip()
        year = str(fields.get("year", "")).strip()
        if author:
            pieces.append(escape_latex(author) + ".")
        if title:
            pieces.append(f"\\textit{{{escape_latex(title)}}}.")
        if year:
            pieces.append(escape_latex(year) + ".")
        entry = " ".join(pieces) if pieces else escape_latex(key)
        out.append(f"\\bibitem{{{key}}} {entry}")
    out.append("\\end{thebibliography}")
    return out


def to_latex(doc: ThesisDocument, sources: dict[Any, SourceLike]) -> str:
    """Render the canonical document to a compilable LaTeX ``article`` string."""
    meta = doc.meta
    title = escape_latex(getattr(meta, "title", "") or "")
    author = ""
    candidate = getattr(meta, "candidate", None)
    if candidate is not None:
        author = escape_latex(getattr(candidate, "name", "") or "")

    out: list[str] = ["\\documentclass{article}"]
    out.append(f"\\title{{{title}}}")
    out.append(f"\\author{{{author}}}")
    out.append("\\begin{document}")
    out.append("\\maketitle")

    for ch in doc.chapters:
        out.append(f"\\section{{{escape_latex(ch.title)}}}")
        for block in ch.blocks:
            rendered = _block_latex(block)
            if rendered:
                out.append(rendered)

    out += _bibliography(doc, sources)
    out.append("\\end{document}")
    return "\n".join(out) + "\n"


__all__ = ["to_latex", "escape_latex"]
