"""Extraction quality gate (eval-first). The corpus is FROZEN append-only —
never delete or soften a case to keep these targets green."""

from __future__ import annotations

from tests.citation_corpus import score


def test_extraction_targets() -> None:
    metrics, rows = score()
    failures = [r for r in rows if r["misses"] or r["fabs"]]
    # ≥90% field recall on hand-labeled ground truth (currently 100%).
    assert metrics["field_recall"] >= 0.90, (metrics, failures[:5])
    # Never-guess is absolute: a wrong concrete value is worse than a flag.
    assert metrics["fabrications"] == [], metrics["fabrications"]
    # Genuinely broken entries must STILL be flagged, not papered over.
    assert metrics["broken_ok"], metrics["broken_flagged"]
