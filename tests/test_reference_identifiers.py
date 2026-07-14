"""Identifier detection and free-text normalization (docs/LLD.md 3.2)."""

from __future__ import annotations

from app.references.identifiers import detect_identifier, normalize_freetext


def test_detects_bare_doi() -> None:
    assert detect_identifier("10.1038/nphys1170") == ("doi", "10.1038/nphys1170")


def test_detects_doi_in_url() -> None:
    kind, value = detect_identifier("https://doi.org/10.1000/xyz123")
    assert kind == "doi"
    assert value == "10.1000/xyz123"


def test_detects_arxiv_new_and_prefixed() -> None:
    assert detect_identifier("1706.03762") == ("arxiv", "1706.03762")
    assert detect_identifier("arXiv:1706.03762") == ("arxiv", "1706.03762")


def test_detects_arxiv_legacy() -> None:
    assert detect_identifier("math.GT/0309136") == ("arxiv", "math.GT/0309136")


def test_detects_isbn_10_and_13() -> None:
    assert detect_identifier("ISBN 0-14-118776-7")[0] == "isbn"
    kind, value = detect_identifier("978-0-14-118776-1")
    assert kind == "isbn"
    assert value == "9780141187761"


def test_free_text_hashes_stably() -> None:
    kind, a = detect_identifier("Achebe, Things Fall Apart, 1958")
    kind2, b = detect_identifier("achebe  things fall apart 1958")
    assert kind == kind2 == "freetext"
    # Normalization makes punctuation/whitespace variants collapse to one key.
    assert a == b
    assert len(a) == 64  # sha256 hex


def test_normalize_freetext_collapses_punctuation() -> None:
    assert normalize_freetext("Woolf, V. — Mrs Dalloway!") == "woolf v mrs dalloway"
