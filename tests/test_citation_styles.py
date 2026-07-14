"""Pluggable citation-style foundation.

Confirms (a) MLA behind the new interface is byte-for-byte identical to the
existing works_cited renderer, (b) IEEE proves the numbered mechanism family,
and (c) the "never guess a field" discipline is preserved across styles.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.renderers import works_cited
from app.renderers.styles import (
    UnknownCitationStyle,
    available_styles,
    get_citation_style,
)
from app.renderers.styles.base import MissingCitationField


@dataclass
class _Src:
    kind: str
    fields: dict


_SOURCES = [
    _Src("book", {"author": "Achebe, Chinua", "title": "Things Fall Apart", "publisher": "Heinemann", "year": "1958"}),
    _Src("journal", {
        "author": "Smith, Jane", "title": "On Something", "container": "Journal of Things",
        "volume": "3", "number": "2", "year": "2020", "pages": "10-20",
    }),
]


def test_mla_style_matches_works_cited_exactly() -> None:
    mla = get_citation_style("mla-9")
    assert mla.mechanism == "author_page"
    # Per-entry parity.
    for src in _SOURCES:
        assert mla.format_reference(src) == works_cited.format_entry(src.kind, src.fields)
    # Full-list parity (alphabetical ordering + repeated-author handling).
    assert mla.sorted_entries(_SOURCES) == works_cited.sorted_entries(_SOURCES)


def test_default_style_is_mla() -> None:
    assert get_citation_style().key == "mla-9"


def test_ieee_numbers_in_order_of_appearance() -> None:
    ieee = get_citation_style("ieee-2021")
    assert ieee.mechanism == "numbered"
    entries = ieee.sorted_entries(_SOURCES)
    assert len(entries) == 2
    # Numbered [1], [2] in the given order (not alphabetised).
    assert entries[0][0].text.startswith("[1] ")
    assert entries[1][0].text.startswith("[2] ")
    # Book title is italicised; journal title is quoted, container italicised.
    assert any(run.italic and run.text == "Things Fall Apart" for run in entries[0])
    assert any(run.italic and run.text == "Journal of Things" for run in entries[1])


def test_ieee_never_guesses_missing_fields() -> None:
    ieee = get_citation_style("ieee-2021")
    incomplete = _Src("book", {"author": "Doe, J.", "title": "Untitled"})  # no publisher/year
    with pytest.raises(MissingCitationField):
        ieee.format_reference(incomplete, ordinal=1)


def test_unknown_style_raises() -> None:
    with pytest.raises(UnknownCitationStyle):
        get_citation_style("chicago-nb-17")  # not yet implemented


def test_available_styles_lists_registered() -> None:
    keys = {s["key"] for s in available_styles()}
    assert {"mla-9", "ieee-2021", "apa-7"} <= keys


def test_apa_is_author_date_and_uses_year_parenthetical() -> None:
    apa = get_citation_style("apa-7")
    assert apa.mechanism == "author_date"
    entry = apa.format_reference(_SOURCES[0])  # Achebe book, 1958
    text = "".join(run.text for run in entry)
    assert "(1958)." in text
    assert any(run.italic and run.text == "Things Fall Apart" for run in entry)


def test_apa_reference_list_is_alphabetical() -> None:
    apa = get_citation_style("apa-7")
    # Given in book(Achebe), journal(Smith) order; APA sorts alphabetically -> Achebe first.
    entries = apa.sorted_entries([_SOURCES[1], _SOURCES[0]])
    first_line = "".join(run.text for run in entries[0])
    assert first_line.startswith("Achebe")


def test_apa_never_guesses_missing_fields() -> None:
    apa = get_citation_style("apa-7")
    incomplete = _Src("journal", {"author": "Smith, J.", "title": "X"})  # missing container/vol/...
    with pytest.raises(MissingCitationField):
        apa.format_reference(incomplete)
