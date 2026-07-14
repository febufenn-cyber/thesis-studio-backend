"""BibTeX import -> registry candidates, and round-trip with the exporter."""

from __future__ import annotations

from app.renderers.bibtex import to_bibtex
from app.renderers.bibtex_import import from_bibtex

_BIB = """
@comment{ this should be ignored }

@article{smith2020,
  author  = {Smith, Jane},
  title   = {On {Nested} Braces},
  journal = {Journal of Testing},
  volume  = {12},
  number  = {3},
  pages   = {45--67},
  year    = "2020",
  doi     = {10.1000/xyz123},
  note    = {ignore me}
}

@book{doe2019,
  author    = {Doe, John},
  title     = {A Fine Book},
  publisher = {Academic Press},
  year      = {2019},
}
"""


class _Src:
    def __init__(self, kind, fields):
        self.kind = kind
        self.fields = fields


def test_article_with_doi_becomes_journal_db():
    art = from_bibtex(_BIB)[0]
    assert art["kind"] == "journal_db"
    assert art["fields"]["doi_or_url"] == "10.1000/xyz123"
    assert art["fields"]["database"] == "imported"
    assert art["fields"]["container"] == "Journal of Testing"
    assert art["fields"]["number"] == "3"


def test_nested_braces_stripped_and_note_dropped():
    art = from_bibtex(_BIB)[0]
    assert art["fields"]["title"] == "On Nested Braces"
    assert "note" not in art["fields"]


def test_book_maps_to_book_kind():
    book = from_bibtex(_BIB)[1]
    assert book["kind"] == "book"
    assert book["fields"] == {
        "author": "Doe, John",
        "title": "A Fine Book",
        "publisher": "Academic Press",
        "year": "2019",
    }


def test_comment_skipped_and_order_preserved():
    assert len(from_bibtex(_BIB)) == 2


def test_round_trip_preserves_author_title_year():
    cands = from_bibtex(_BIB)
    sources = [_Src(c["kind"], c["fields"]) for c in cands]
    out = from_bibtex(to_bibtex(sources))
    for before, after in zip(cands, out):
        for k in ("author", "title", "year"):
            assert after["fields"][k] == before["fields"][k]
