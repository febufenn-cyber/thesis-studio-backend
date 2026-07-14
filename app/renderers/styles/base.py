"""Pluggable citation-style interface.

Acadensia's integrity core (registry, verifier, "never guess a field") is
citation-style-agnostic; only the *surface* — how a verified source becomes a
formatted reference and an in-text marker — varies by discipline. This module
defines that surface so styles from all three mechanism families (author-date /
author-page, numbered, notes) share one contract. See docs/DOMAIN_EXPANSION.md.

Every style formats to canonical ``Run`` lists (not strings) so the same output
feeds the docx/md/txt renderers, exactly as the MLA implementation already does.
Missing required fields raise ``MissingCitationField`` — bibliographic data is
never invented.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

from app.canonical.model import Run

# Re-exported so callers depend on the interface module, not the MLA renderer.
from app.renderers.works_cited import MissingCitationField, SourceLike

CitationMechanism = Literal["author_page", "author_date", "numbered", "notes"]


@runtime_checkable
class CitationStyle(Protocol):
    """A citation style: a mechanism family plus reference/ordering formatting."""

    key: str  # stable id, e.g. "mla-9", "ieee-2021"
    edition: str  # human label, e.g. "MLA 9th (2021)"
    mechanism: CitationMechanism

    def required_fields(self, source_type: str) -> tuple[str, ...]:
        """Fields that must be present for this source type, else the verifier flags it."""

    def format_reference(self, source: SourceLike, ordinal: int | None = None) -> list[Run]:
        """One reference-list entry as canonical Runs. ``ordinal`` is the 1-based
        position for numbered styles (ignored by author-date/page styles)."""

    def sorted_entries(self, sources: list[SourceLike]) -> list[list[Run]]:
        """The full reference list in this style's canonical order (alphabetical
        for author-date/page; order-of-appearance for numbered)."""


__all__ = [
    "CitationMechanism",
    "CitationStyle",
    "MissingCitationField",
    "Run",
    "SourceLike",
    "Any",
]
