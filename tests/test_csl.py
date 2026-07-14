"""CSL-JSON export (Zotero/citeproc interchange)."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.renderers.csl import to_csl_json


@dataclass
class _Src:
    kind: str
    fields: dict = field(default_factory=dict)


def _one(kind: str, fields: dict) -> dict:
    items = to_csl_json([_Src(kind, fields)])
    assert len(items) == 1
    return items[0]


def test_journal_maps_to_article_journal_with_all_fields():
    item = _one("journal", {
        "author": "Woolf, Virginia", "title": "Modern Fiction",
        "container": "The Common Reader", "volume": "1", "number": "3",
        "year": "1925", "pages": "150-158",
    })
    assert item["type"] == "article-journal"
    assert item["container-title"] == "The Common Reader"
    assert item["issue"] == "3"
    assert item["page"] == "150-158"
    assert item["author"] == [{"family": "Woolf", "given": "Virginia"}]
    assert item["issued"] == {"date-parts": [[1925]]}


def test_book_maps_to_book_type():
    item = _one("book", {"author": "Austen, Jane", "title": "Emma", "publisher": "John Murray", "year": "1815"})
    assert item["type"] == "book"
    assert item["publisher"] == "John Murray"


def test_verify_publisher_is_omitted():
    item = _one("book", {"author": "Austen, Jane", "title": "Emma", "publisher": "[VERIFY] John Murray", "year": "1815"})
    assert "publisher" not in item


def test_multiple_authors_parse_to_two_objects():
    item = _one("journal", {
        "author": "Smith, J. and Doe, A.", "title": "A Study",
        "container": "Journal of Things", "volume": "2", "number": "4",
        "year": "2001", "pages": "1-10",
    })
    assert item["author"] == [
        {"family": "Smith", "given": "J."},
        {"family": "Doe", "given": "A."},
    ]


def test_journal_db_doi_is_emitted():
    item = _one("journal_db", {
        "author": "Borges, Jorge Luis", "title": "El Aleph", "container": "Sur",
        "volume": "9", "number": "1", "year": "1945", "pages": "5-20",
        "doi_or_url": "10.1000/xyz123",
    })
    assert item["DOI"] == "10.1000/xyz123"


def test_id_disambiguation():
    src = {
        "author": "Woolf, Virginia", "title": "T", "container": "C",
        "volume": "1", "number": "1", "year": "1925", "pages": "1-2",
    }
    items = to_csl_json([_Src("journal", dict(src)), _Src("journal", dict(src))])
    assert [it["id"] for it in items] == ["Woolf1925", "Woolf1925a"]
