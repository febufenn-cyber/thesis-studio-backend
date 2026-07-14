"""Domain citation styles built in parallel: Vancouver, ACS, AMA, CSE,
Chicago author-date, ASCE. One consolidated contract test across all six.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.renderers.styles import available_styles, get_citation_style
from app.renderers.styles.base import MissingCitationField


@dataclass
class _Src:
    kind: str
    fields: dict


_BOOK = _Src("book", {"author": "Achebe, Chinua", "title": "Things Fall Apart", "publisher": "Heinemann", "year": "1958"})
_JOURNAL = _Src("journal", {
    "author": "Smith, Jane", "title": "On Something", "container": "J. Things",
    "volume": "3", "number": "2", "year": "2020", "pages": "10-20",
})

_NEW_STYLES = [
    "vancouver-icmje", "acs-2020", "ama-11", "cse-8-nameyear", "chicago-ad-17", "asce",
    "aip", "asme",
]
_NUMBERED = ["vancouver-icmje", "acs-2020", "ama-11", "aip", "asme"]
_AUTHOR_DATE = ["cse-8-nameyear", "chicago-ad-17", "asce"]


@pytest.mark.parametrize("key", _NEW_STYLES)
def test_style_registered_and_formats(key: str) -> None:
    style = get_citation_style(key)
    assert style.key == key
    for src in (_BOOK, _JOURNAL):
        runs = style.format_reference(src, ordinal=1)
        assert runs and "".join(r.text for r in runs).strip()


@pytest.mark.parametrize("key", _NEW_STYLES)
def test_style_never_guesses_missing_fields(key: str) -> None:
    style = get_citation_style(key)
    incomplete = _Src("book", {"author": "Doe, J.", "title": "X"})  # no publisher/year
    with pytest.raises(MissingCitationField):
        style.format_reference(incomplete, ordinal=1)


@pytest.mark.parametrize("key", _NUMBERED)
def test_numbered_styles_number_in_order_of_appearance(key: str) -> None:
    style = get_citation_style(key)
    assert style.mechanism == "numbered"
    entries = style.sorted_entries([_JOURNAL, _BOOK])
    assert entries[0][0].text.startswith("[1] ")
    assert entries[1][0].text.startswith("[2] ")


@pytest.mark.parametrize("key", _AUTHOR_DATE)
def test_author_date_styles_are_alphabetical(key: str) -> None:
    style = get_citation_style(key)
    assert style.mechanism == "author_date"
    # Given journal(Smith) then book(Achebe); alphabetical -> Achebe first.
    entries = style.sorted_entries([_JOURNAL, _BOOK])
    assert "".join(r.text for r in entries[0]).startswith("Achebe")


def test_all_new_styles_are_listed() -> None:
    keys = {s["key"] for s in available_styles()}
    assert set(_NEW_STYLES) <= keys
    # Full catalogue is now 11 styles across three mechanism families.
    assert len(keys) >= 11
