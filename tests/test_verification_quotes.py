"""Verbatim matching, normalization, extractors (docs/LLD.md 3.3)."""

from __future__ import annotations

import pytest

from app.verification.extractors.base import ExtractedDoc, ExtractorError, PageText
from app.verification.extractors.registry import get_extractor
from app.verification.extractors.text import HtmlExtractor, PlainTextExtractor
from app.verification.normalize import normalize
from app.verification.quotes import find_best_span, verify_against_doc


def test_normalize_folds_smart_punctuation() -> None:
    assert normalize("“A—study… of ﬁction”") == normalize('"a-study... of fiction"')


def test_exact_match_is_verified() -> None:
    result = find_best_span(
        "A study of Mrs Dalloway",
        "In this book, a study of Mrs Dalloway is presented.",
    )
    assert result.status == "verified"
    assert result.score == 1.0


def test_single_typo_is_drift() -> None:
    result = find_best_span("a study of Mrs Dallowey", "a study of Mrs Dalloway is here")
    assert result.status == "drift"
    assert 0.85 <= result.score < 0.97


def test_unrelated_text_is_not_found() -> None:
    result = find_best_span("completely different sentence", "a study of Mrs Dalloway")
    assert result.status == "not_found"


def test_locator_match_and_mismatch() -> None:
    doc = ExtractedDoc(
        pages=[PageText("41", "nothing relevant"), PageText("42", "a study of Mrs Dalloway appears")]
    )
    ok, findings = verify_against_doc("a study of Mrs Dalloway", "42", doc)
    assert ok.status == "verified"
    assert ok.matched_locator == "42"
    assert findings == []

    _, mismatch = verify_against_doc("a study of Mrs Dalloway", "p. 10", doc)
    assert any(f.rule == "quote_locator_mismatch" for f in mismatch)


def test_plain_text_extractor() -> None:
    doc = PlainTextExtractor().extract(b"Hello world text.")
    assert doc.pages[0].text.startswith("Hello world")
    with pytest.raises(ExtractorError):
        PlainTextExtractor().extract(b"   ")


def test_html_extractor_strips_tags_and_scripts() -> None:
    html = b"<html><body><script>bad()</script><p>Real content here</p></body></html>"
    doc = HtmlExtractor().extract(html)
    assert "Real content here" in doc.full_text
    assert "bad()" not in doc.full_text


def test_registry_unknown_mime_raises() -> None:
    with pytest.raises(ExtractorError):
        get_extractor("application/x-unknown")
