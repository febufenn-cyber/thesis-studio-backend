"""Reconciliation: merge, confidence, tie-break, canonical_key (docs/LLD.md 3.2)."""

from __future__ import annotations

import pytest

from app.references.reconcile import canonical_key, merge
from app.references.resolvers.base import ResolvedRecord


def _rec(authority: str, kind: str | None = "journal", **fields) -> ResolvedRecord:
    rec = ResolvedRecord(
        identifier_kind="doi",
        identifier_value="10.0/x",
        authority=authority,
        registry_kind=kind,
        matched=True,
    )
    for name, (value, conf) in fields.items():
        rec.add(name, value, conf)
    return rec


def test_merge_picks_highest_confidence_value() -> None:
    a = _rec("crossref", title=("Real Title", 0.98))
    b = _rec("openalex", title=("Approx Title", 0.90))
    merged = merge([a, b])
    assert merged.fields["title"].value == "Real Title"
    assert merged.fields["title"].authority == "crossref"


def test_agreement_boosts_confidence() -> None:
    a = _rec("crossref", year=("1925", 0.90))
    b = _rec("openalex", year=("1925", 0.90))
    merged = merge([a, b])
    # Two authorities agree -> confidence lifted above the single-source value.
    assert merged.fields["year"].confidence > 0.90


def test_tie_break_prefers_higher_authority_rank() -> None:
    a = _rec("openalex", publisher=("OUP", 0.80))
    b = _rec("crossref", publisher=("Oxford University Press", 0.80))
    merged = merge([a, b])
    # Equal confidence -> Crossref (higher rank) wins.
    assert merged.fields["publisher"].authority == "crossref"


def test_merge_prefers_registry_kind_from_higher_authority() -> None:
    a = _rec("openalex", kind="web", title=("T", 0.8))
    b = _rec("crossref", kind="journal", title=("T", 0.9))
    merged = merge([a, b])
    assert merged.registry_kind == "journal"
    assert merged.source_type == "article"


def test_merge_requires_a_matched_record() -> None:
    with pytest.raises(ValueError):
        merge([])


def test_canonical_key_collapses_variants() -> None:
    a = _rec(
        "crossref",
        author=("Achebe, Chinua", 0.9),
        year=("1958", 0.9),
        title=("Things Fall Apart", 0.9),
    )
    b = _rec(
        "openalex",
        author=("Achebe, Chinua and Someone, Else", 0.8),
        year=("1958", 0.8),
        title=("Things Fall Apart!", 0.8),
    )
    assert canonical_key(a) == canonical_key(b)
