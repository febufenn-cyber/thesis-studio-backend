"""Bluebook (US) and OSCOLA (UK) legal citation styles — notes mechanism."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.renderers.styles import get_citation_style


@dataclass
class _Src:
    kind: str
    fields: dict = field(default_factory=dict)


def _book(author, title):
    return _Src("book", {"author": author, "title": title, "publisher": "Harvard UP", "year": "1991"})


def _journal(author, title):
    return _Src("journal", {
        "author": author, "title": title, "container": "Yale LJ",
        "volume": "100", "number": "1", "year": "1990", "pages": "1",
    })


def test_bluebook_is_notes_and_note_has_italic_title():
    style = get_citation_style("bluebook-21")
    assert style.mechanism == "notes"
    note = style.format_note(_book("Ackerman, Bruce", "We the People"))
    assert note[0].text.startswith("Ackerman, Bruce, ")
    assert any(r.italic and r.text == "We the People" for r in note)


def test_bluebook_bibliography_alphabetical():
    style = get_citation_style("bluebook-21")
    entries = style.sorted_entries([_book("Zephyr, A.", "Winds"), _book("Abbott, B.", "Anchors")])
    assert entries[0][0].text.startswith("Abbott")


def test_oscola_is_notes_and_journal_note_format():
    style = get_citation_style("oscola-4")
    assert style.mechanism == "notes"
    note = style.format_note(_journal("Ronald Dworkin", "Hard Cases"))
    assert note[0].text.startswith("Ronald Dworkin, 'Hard Cases' (1990) 100 ")
    assert any(r.italic and r.text == "Yale LJ" for r in note)


def test_oscola_bibliography_alphabetical():
    style = get_citation_style("oscola-4")
    entries = style.sorted_entries([_book("Zephyr, A.", "Winds"), _book("Abbott, B.", "Anchors")])
    assert entries[0][0].text.startswith("Abbott")
