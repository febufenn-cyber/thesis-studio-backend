"""LaTeX and CSL-JSON import (docs/LLD.md 3.5)."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

import pytest

from app.canonical.model import ThesisDocument, ThesisMeta, WorksCitedRef
from app.importers.csl_import import from_csl_json
from app.importers.latex_import import UnsupportedLatexError, from_latex
from app.renderers.csl import to_csl_json
from app.renderers.latex import to_latex


@dataclass
class _Src:
    kind: str
    fields: dict


def test_latex_import_parses_sections_and_italics() -> None:
    latex = (
        r"\documentclass{article}\title{My Title}\author{Jane Doe}"
        r"\begin{document}\maketitle"
        r"\section{Introduction}Hello \textit{world} here." "\n\n"
        r"Second paragraph.\subsection{Sub}Body."
        r"\end{document}"
    )
    doc = from_latex(latex)
    assert doc.meta.title == "My Title"
    assert doc.meta.candidate.name == "Jane Doe"
    assert len(doc.chapters) == 1
    assert doc.chapters[0].title == "Introduction"
    types = [b.type for b in doc.chapters[0].blocks]
    assert "paragraph" in types and "heading" in types
    # italic run preserved
    para = next(b for b in doc.chapters[0].blocks if b.type == "paragraph")
    assert any(r.italic and r.text == "world" for r in para.runs)


def test_latex_import_cite_becomes_source_needed_marker() -> None:
    latex = r"\begin{document}\section{S}A claim \cite{smith2020}.\end{document}"
    doc = from_latex(latex)
    markers = [b for b in doc.chapters[0].blocks if b.type == "marker"]
    assert markers and markers[0].kind == "SOURCE_NEEDED"


def test_latex_import_fails_closed_on_unsupported_macro() -> None:
    with pytest.raises(UnsupportedLatexError):
        from_latex(r"\begin{document}\includegraphics{fig.png}\end{document}")


def test_latex_round_trip_preserves_title_and_text() -> None:
    doc = ThesisDocument(
        meta=ThesisMeta(title="Round Trip"),
        chapters=[{
            "number": 1, "title": "Chapter One",
            "blocks": [{"type": "paragraph", "runs": [{"text": "plain and "}, {"text": "italic", "italic": True}]}],
        }],
    )
    latex = to_latex(doc, {})
    reparsed = from_latex(latex)
    assert reparsed.meta.title == "Round Trip"
    assert reparsed.chapters[0].title == "Chapter One"
    para = next(b for b in reparsed.chapters[0].blocks if b.type == "paragraph")
    assert any(r.italic and r.text == "italic" for r in para.runs)


def test_csl_round_trip() -> None:
    src = _Src("journal", {
        "author": "Woolf, Virginia", "title": "Modern Fiction", "container": "The Common Reader",
        "volume": "1", "number": "3", "year": "1925", "pages": "150-158",
    })
    items = to_csl_json([src])
    candidates = from_csl_json(__import__("json").dumps(items))
    assert len(candidates) == 1
    fields = candidates[0]["fields"]
    assert fields["title"] == "Modern Fiction"
    assert fields["author"] == "Woolf, Virginia"
    assert fields["container"] == "The Common Reader"


def test_csl_import_ignores_verify_and_empty() -> None:
    assert from_csl_json("not json") == []
    assert from_csl_json("[{}]") == []
