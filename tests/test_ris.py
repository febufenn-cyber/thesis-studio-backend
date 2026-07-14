"""RIS export/import for reference managers (Zotero/EndNote/Mendeley)."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.renderers.ris import from_ris, to_ris


@dataclass
class _Src:
    kind: str
    fields: dict = field(default_factory=dict)


def test_to_ris_journal_and_book_tags():
    journal = _Src("journal", {
        "author": "Smith, Jane", "title": "On Things", "year": "2020",
        "container": "Journal of Things", "volume": "3", "number": "2",
        "pages": "10-20",
    })
    book = _Src("book", {
        "author": "Doe, John", "title": "A Book", "year": "1999",
        "publisher": "Acme Press",
    })
    out = to_ris([journal, book])
    assert "TY  - JOUR" in out
    assert "AU  - Smith, Jane" in out
    assert "TI  - On Things" in out
    assert "PY  - 2020" in out
    assert "SP  - 10" in out and "EP  - 20" in out
    assert "SP  - 10-20" not in out
    assert out.count("ER  - ") == 2
    assert "TY  - BOOK" in out
    assert "PB  - Acme Press" in out


def test_from_ris_parses_kinds_and_fields():
    text = (
        "TY  - JOUR\r\n"
        "  AU  - Smith, Jane\r\n"
        "TI  - On Things\r\n"
        "PY  - 2020\r\n"
        "JO  - Journal of Things\r\n"
        "VL  - 3\r\n"
        "IS  - 2\r\n"
        "SP  - 10\r\n"
        "EP  - 20\r\n"
        "DO  - 10.1/x\r\n"
        "ER  - \r\n"
    )
    [cand] = from_ris(text)
    assert cand["kind"] == "journal"
    f = cand["fields"]
    assert f["author"] == "Smith, Jane"
    assert f["container"] == "Journal of Things"
    assert f["volume"] == "3" and f["number"] == "2"
    assert f["pages"] == "10-20"
    assert f["doi_or_url"] == "10.1/x"


def test_from_ris_maps_elec_to_web():
    [cand] = from_ris("TY  - ELEC\nTI  - A Page\nUR  - http://x.test\nER  - \n")
    assert cand["kind"] == "web"
    assert cand["fields"]["url"] == "http://x.test"
    assert "pages" not in cand["fields"]


def test_roundtrip_preserves_core_fields():
    src = _Src("journal", {
        "author": "Smith, Jane", "title": "On Things", "year": "2020",
        "container": "Journal of Things", "volume": "3", "number": "2",
        "pages": "10-20",
    })
    [cand] = from_ris(to_ris([src]))
    assert cand["kind"] == "journal"
    for key in ("author", "title", "year", "container"):
        assert cand["fields"][key] == src.fields[key]
    assert cand["fields"]["pages"] == "10-20"
