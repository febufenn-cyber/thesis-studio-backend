"""BibTeX export of the citation registry."""

from __future__ import annotations

from dataclasses import dataclass

from app.renderers.bibtex import to_bibtex


@dataclass
class _Src:
    kind: str
    fields: dict


def test_book_becomes_book_entry_with_cite_key() -> None:
    src = _Src("book", {"author": "Achebe, Chinua", "title": "Things Fall Apart", "publisher": "Heinemann", "year": "1958"})
    out = to_bibtex([src])
    assert out.startswith("@book{Achebe1958,")
    assert "author = {Achebe, Chinua}," in out
    assert "title = {Things Fall Apart}," in out
    assert "publisher = {Heinemann}," in out
    assert "year = {1958}," in out


def test_journal_becomes_article_entry() -> None:
    src = _Src("journal", {
        "author": "Smith, Jane", "title": "On Something", "container": "Journal of Things",
        "volume": "3", "number": "2", "year": "2020", "pages": "10-20",
    })
    out = to_bibtex([src])
    assert out.startswith("@article{Smith2020,")
    assert "journal = {Journal of Things}," in out
    assert "volume = {3}," in out
    assert "pages = {10-20}," in out


def test_missing_and_unverified_fields_are_omitted() -> None:
    src = _Src("book", {"author": "Doe, J.", "title": "X", "publisher": "[VERIFY]"})
    out = to_bibtex([src])
    assert "author = {Doe, J.}," in out
    assert "publisher" not in out  # [VERIFY] and absent fields are not emitted
    assert "year" not in out


def test_cite_key_collisions_are_disambiguated() -> None:
    a = _Src("book", {"author": "Roy, A.", "title": "One", "year": "1997"})
    b = _Src("book", {"author": "Roy, A.", "title": "Two", "year": "1997"})
    out = to_bibtex([a, b])
    assert "@book{Roy1997," in out
    assert "@book{Roy1997a," in out


def test_empty_registry_yields_empty_string() -> None:
    assert to_bibtex([]) == ""
