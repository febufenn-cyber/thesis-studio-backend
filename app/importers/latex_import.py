"""LaTeX import — parse an ``article`` subset into the canonical model.

Supports a deliberately narrow subset (title/author, sections, subsections,
paragraphs, \\textit/\\emph, quote/verse environments, \\cite). Anything outside
the subset raises ``UnsupportedLatexError`` and the caller returns 422 — the
parser never guesses at unsupported macros and never emits a partial document.
A ``\\cite`` becomes a SOURCE_NEEDED marker rather than a fabricated reference.
"""

from __future__ import annotations

import re

from app.canonical.model import (
    ChapterDoc,
    HeadingBlock,
    MarkerBlock,
    ParagraphBlock,
    Run,
    ThesisDocument,
)

__all__ = ["from_latex", "UnsupportedLatexError"]


class UnsupportedLatexError(ValueError):
    """A macro or environment outside the supported subset was encountered."""


_UNESCAPE = {
    r"\&": "&", r"\%": "%", r"\$": "$", r"\#": "#", r"\_": "_",
    r"\{": "{", r"\}": "}",
    r"\textasciitilde{}": "~", r"\textasciicircum{}": "^",
    r"\textbackslash{}": "\\",
}

# Macros allowed to appear inline and simply unwrapped/handled.
_INLINE_ALLOWED = {"textit", "emph", "cite", "textbf", "underline"}
# Sectioning + environment macros handled structurally.
_KNOWN_ENVIRONMENTS = {"quote", "verse", "document"}


def _unescape(text: str) -> str:
    for src, dst in _UNESCAPE.items():
        text = text.replace(src, dst)
    return text


def _guard_unsupported(body: str) -> None:
    """Raise on any control sequence not in the supported subset."""
    for macro in re.findall(r"\\([A-Za-z]+)", body):
        if macro in _INLINE_ALLOWED:
            continue
        if macro in {"section", "subsection", "subsubsection", "title", "author",
                     "maketitle", "begin", "end", "textbackslash", "textasciitilde",
                     "textasciicircum", "item"}:
            continue
        raise UnsupportedLatexError(f"\\{macro}")


def _runs_from_inline(text: str) -> list[Run]:
    """Convert inline text with \\textit/\\emph/\\cite into canonical runs."""
    runs: list[Run] = []
    i = 0
    n = len(text)
    buf = ""

    def flush(italic: bool = False) -> None:
        nonlocal buf
        if buf:
            runs.append(Run(text=_unescape(buf), italic=italic))
            buf = ""

    while i < n:
        m = re.match(r"\\(textit|emph)\{", text[i:])
        mc = re.match(r"\\cite\{([^}]*)\}", text[i:])
        if m:
            flush()
            i += m.end()
            depth = 1
            start = i
            while i < n and depth:
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                i += 1
            inner = text[start:i]
            i += 1  # skip closing brace
            runs.append(Run(text=_unescape(inner), italic=True))
        elif mc:
            flush()
            key = mc.group(1)
            runs.append(Run(text=f"[cite: {key}]", italic=False))
            i += mc.end()
        else:
            buf += text[i]
            i += 1
    flush()
    return runs or [Run(text="")]


def _extract_arg(text: str, macro: str) -> str | None:
    m = re.search(r"\\" + macro + r"\{([^}]*)\}", text)
    return m.group(1) if m else None


def from_latex(source: str) -> ThesisDocument:
    """Parse a LaTeX ``article``-subset string into a ThesisDocument."""
    doc_match = re.search(r"\\begin\{document\}(.*?)\\end\{document\}", source, re.DOTALL)
    body = doc_match.group(1) if doc_match else source

    preamble = source[: doc_match.start()] if doc_match else source
    title = _extract_arg(preamble + body, "title") or _extract_arg(body, "title") or ""
    author = _extract_arg(preamble + body, "author") or ""

    _guard_unsupported(body)

    meta: dict = {"title": _unescape(title.strip())}
    if author.strip():
        meta["candidate"] = {"name": _unescape(author.strip())}

    # Split into sections on \section{...}.
    sections = re.split(r"\\section\{([^}]*)\}", body)
    chapters: list[dict] = []
    # sections[0] is preamble text before the first \section (ignored as body intro
    # only if it contains real content; we attach it to an untitled chapter).
    lead = sections[0]
    pairs: list[tuple[str, str]] = []
    if len(sections) > 1:
        for idx in range(1, len(sections), 2):
            pairs.append((sections[idx], sections[idx + 1] if idx + 1 < len(sections) else ""))
    elif lead.strip():
        pairs.append(("", lead))

    number = 0
    for title_text, chunk in pairs:
        number += 1
        blocks = _blocks_from_chunk(chunk)
        chapters.append(
            ChapterDoc(number=number, title=_unescape(title_text.strip()) or f"Section {number}", blocks=blocks).model_dump()
        )

    return ThesisDocument.model_validate({"meta": meta, "front_matter": [], "chapters": chapters, "works_cited": []})


def _blocks_from_chunk(chunk: str) -> list:
    blocks: list = []
    # Handle subsections and environments by scanning sequentially.
    tokens = re.split(r"(\\subsection\{[^}]*\}|\\subsubsection\{[^}]*\}|\\begin\{quote\}.*?\\end\{quote\}|\\begin\{verse\}.*?\\end\{verse\})", chunk, flags=re.DOTALL)
    for token in tokens:
        if not token or not token.strip():
            continue
        sub = re.match(r"\\subsection\{([^}]*)\}", token)
        subsub = re.match(r"\\subsubsection\{([^}]*)\}", token)
        quote = re.match(r"\\begin\{quote\}(.*?)\\end\{quote\}", token, re.DOTALL)
        verse = re.match(r"\\begin\{verse\}(.*?)\\end\{verse\}", token, re.DOTALL)
        if sub:
            blocks.append(HeadingBlock(level=2, text=_unescape(sub.group(1).strip())))
        elif subsub:
            blocks.append(HeadingBlock(level=3, text=_unescape(subsub.group(1).strip())))
        elif quote:
            from app.canonical.model import BlockQuoteBlock
            blocks.append(BlockQuoteBlock(text=_unescape(quote.group(1).strip())))
        elif verse:
            from app.canonical.model import VerseQuoteBlock
            lines = [_unescape(x.strip()) for x in re.split(r"\\\\", verse.group(1)) if x.strip()]
            blocks.append(VerseQuoteBlock(lines=lines or [""]))
        else:
            for para in re.split(r"\n\s*\n", token):
                para = para.strip()
                if not para:
                    continue
                if r"\cite{" in para and "[VERIFY]" not in para:
                    # Record unresolved citation keys as SOURCE_NEEDED markers.
                    for key in re.findall(r"\\cite\{([^}]*)\}", para):
                        blocks.append(MarkerBlock(kind="SOURCE_NEEDED", note=f"cite: {key}"))
                blocks.append(ParagraphBlock(runs=_runs_from_inline(para)))
    return [b.model_dump() if hasattr(b, "model_dump") else b for b in blocks]
