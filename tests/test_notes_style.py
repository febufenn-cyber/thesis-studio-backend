"""Chicago Notes-Bibliography style + the footnote engine (notes mechanism)."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.renderers.styles import get_citation_style
from app.renderers.styles.notes_engine import build_notes


@dataclass
class _Src:
    kind: str
    fields: dict = field(default_factory=dict)


def _book(author, title):
    return _Src("book", {"author": author, "title": title, "publisher": "Verso", "year": "2019"})


def test_chicago_nb_mechanism_is_notes():
    assert get_citation_style("chicago-nb-17").mechanism == "notes"


def test_chicago_nb_bibliography_is_alphabetical():
    style = get_citation_style("chicago-nb-17")
    entries = style.sorted_entries([_book("Zephyr, A.", "Winds"), _book("Abbott, B.", "Anchors")])
    assert entries[0][0].text.startswith("Abbott")


def test_chicago_nb_reference_book_has_italic_title():
    style = get_citation_style("chicago-nb-17")
    runs = style.format_reference(_book("Abbott, B.", "Anchors"))
    assert any(r.italic and r.text == "Anchors" for r in runs)
    assert runs[-1].text.endswith("Verso, 2019.")


def test_build_notes_numbers_and_ibid_on_immediate_repeat():
    style = get_citation_style("chicago-nb-17")
    a = _book("Abbott, B.", "Anchors")
    b = _book("Zephyr, A.", "Winds")
    notes = build_notes([a, a, b], style)
    assert [n[0].text for n in notes] == ["1. ", "2. ", "3. "]
    assert notes[1][1].text == "Ibid."  # immediate repeat of a
    assert notes[2][1].text.startswith("Zephyr")  # b's full note


def test_build_notes_non_adjacent_repeat_uses_short_form():
    style = get_citation_style("chicago-nb-17")
    a = _book("Abbott, B.", "Anchors")
    b = _book("Zephyr, A.", "Winds")
    notes = build_notes([a, b, a], style)  # a repeats non-adjacently
    assert notes[2][1].text == "Abbott, "  # short form: Last, Short-Title.
