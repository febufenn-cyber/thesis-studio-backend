"""LaTeX export from the canonical document."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from app.canonical.model import (
    ChapterDoc,
    ParagraphBlock,
    Run,
    ThesisDocument,
    ThesisMeta,
    WorksCitedRef,
)
from app.renderers.latex import escape_latex, to_latex


@dataclass
class _Src:
    kind: str
    fields: dict


def test_to_latex_smoke():
    ref = WorksCitedRef(source_id=uuid4())
    doc = ThesisDocument(
        meta=ThesisMeta(title="On Woolf", candidate={"name": "Jane Doe"}),
        chapters=[
            ChapterDoc(
                number=1,
                title="Introduction",
                blocks=[
                    ParagraphBlock(
                        runs=[
                            Run(text="A study of "),
                            Run(text="Mrs Dalloway", italic=True),
                            Run(text="."),
                        ]
                    )
                ],
            )
        ],
        works_cited=[ref],
    )
    sources = {
        ref.source_id: _Src(
            kind="book",
            fields={"author": "Woolf, Virginia", "title": "Mrs Dalloway", "year": "1925"},
        )
    }
    out = to_latex(doc, sources)
    assert "\\documentclass" in out
    assert "\\section{" in out
    assert "\\textit{" in out
    assert "\\begin{thebibliography}" in out
    assert "\\bibitem" in out


def test_escape_latex_ampersand():
    assert escape_latex("A & B") == "A \\& B"
