"""Inline-quote extraction quality gate. Corpus frozen append-only."""

from __future__ import annotations

from tests.quote_corpus import score


def test_quote_extraction_targets() -> None:
    metrics, rows = score()
    failures = [r for r in rows if r["misses"] or r["fabs"]]
    assert metrics["recall"] >= 0.80, (metrics, failures[:5])
    # A wrong link or a captured must-skip is a fabrication: zero tolerance.
    assert metrics["fabrications"] == [], metrics["fabrications"]
