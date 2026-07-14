"""Reconcile records from multiple authorities into one merged resolution.

Per field, pick the highest-confidence value, break ties by static authority
rank, and boost confidence when independent authorities agree. Group variants of
the same work under a stable ``canonical_key`` so the same reference cited three
ways collapses to one record.
"""

from __future__ import annotations

import re

from app.references.resolvers import AUTHORITY_RANK
from app.references.resolvers.base import FieldValue, ResolvedRecord
from app.renderers.source_types import source_type_for_kind

__all__ = ["merge", "canonical_key"]


def _rank(authority: str) -> int:
    return AUTHORITY_RANK.get(authority, 0)


def merge(records: list[ResolvedRecord]) -> ResolvedRecord:
    """Merge authority records into one, keeping the winning authority per field."""
    real = [r for r in records if r is not None and r.matched]
    if not real:
        raise ValueError("merge() requires at least one matched record")

    base = real[0]
    merged = ResolvedRecord(
        identifier_kind=base.identifier_kind,
        identifier_value=base.identifier_value,
        authority="merged",
        matched=True,
    )

    # registry_kind: prefer the highest-rank authority that supplied one.
    for rec in sorted(real, key=lambda r: _rank(r.authority), reverse=True):
        if rec.registry_kind:
            merged.registry_kind = rec.registry_kind
            break
    if merged.registry_kind:
        merged.source_type = source_type_for_kind(merged.registry_kind)

    field_names = {name for rec in real for name in rec.fields}
    for name in field_names:
        candidates: list[FieldValue] = [
            rec.fields[name] for rec in real if name in rec.fields
        ]
        best = max(candidates, key=lambda fv: (fv.confidence, _rank(fv.authority)))
        agree = sum(
            1 for fv in candidates if fv.value.strip().lower() == best.value.strip().lower()
        )
        boosted = min(1.0, best.confidence + 0.02 * (agree - 1))
        merged.fields[name] = FieldValue(
            value=best.value, authority=best.authority, confidence=boosted, raw=best.raw
        )

    for rec in real:
        if rec.retraction:
            merged.retraction = rec.retraction
            break
    return merged


def canonical_key(rec: ResolvedRecord) -> str:
    """Collapse key for dedup: first-author surname | year | normalized title."""
    author = rec.fields.get("author")
    surname = ""
    if author:
        first = author.value.split(" and ")[0]
        surname = first.split(",")[0].strip().lower()
    year = rec.fields.get("year")
    year_val = year.value.strip() if year else ""
    title = rec.fields.get("title")
    title_norm = ""
    if title:
        title_norm = re.sub(r"[^\w\s]", "", title.value.lower())
        title_norm = re.sub(r"\s+", " ", title_norm).strip()[:60]
    return f"{surname}|{year_val}|{title_norm}"
