"""Extract a styled paragraph stream from a .docx manuscript.

The stream is the deterministic input to structure.py. The author's text is
preserved byte-for-byte inside runs; only presentation metadata is derived.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from docx import Document


@dataclass
class ExtractedRun:
    text: str
    italic: bool = False
    bold: bool = False


@dataclass
class ExtractedPara:
    """One manuscript paragraph with the presentation facts classification needs."""

    index: int
    runs: list[ExtractedRun] = field(default_factory=list)
    style_name: str = ""
    alignment: str = ""          # "", "left", "center", "right", "justify"
    left_indent_in: float = 0.0
    first_line_indent_in: float = 0.0
    all_caps: bool = False       # visual caps: every cased char uppercase
    mostly_bold: bool = False
    page_break_before: bool = False

    @property
    def text(self) -> str:
        return "".join(r.text for r in self.runs)


_ALIGN = {0: "left", 1: "center", 2: "right", 3: "justify"}


def extract_paragraphs(docx_path: str) -> list[ExtractedPara]:
    """Read *docx_path* into a flat paragraph stream (empty paragraphs dropped)."""
    doc = Document(docx_path)
    out: list[ExtractedPara] = []
    for i, p in enumerate(doc.paragraphs):
        text = p.text
        if not text.strip():
            continue
        runs = [
            ExtractedRun(
                text=r.text,
                italic=bool(r.italic or (r.font.italic if r.font else False)),
                bold=bool(r.bold or (r.font.bold if r.font else False)),
            )
            for r in p.runs
            if r.text
        ] or [ExtractedRun(text=text)]

        pf = p.paragraph_format
        li = pf.left_indent.inches if pf.left_indent else 0.0
        fli = pf.first_line_indent.inches if pf.first_line_indent else 0.0
        cased = [c for c in text if c.isalpha()]
        bold_chars = sum(len(r.text) for r in runs if r.bold)

        out.append(ExtractedPara(
            index=i,
            runs=runs,
            style_name=p.style.name if p.style else "",
            alignment=_ALIGN.get(
                int(pf.alignment) if pf.alignment is not None else -1, ""
            ),
            left_indent_in=round(li, 2),
            first_line_indent_in=round(fli, 2),
            all_caps=bool(cased) and all(c.isupper() for c in cased),
            mostly_bold=bool(text.strip()) and bold_chars >= 0.7 * len(text),
            page_break_before=bool(pf.page_break_before),
        ))
    return out
