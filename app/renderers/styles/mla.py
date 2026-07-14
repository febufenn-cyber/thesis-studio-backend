"""MLA 9th edition — the first CitationStyle (author-page mechanism).

Wraps the existing, battle-tested ``works_cited`` renderer rather than
reimplementing it, so current MLA output is byte-for-byte unchanged and the
existing renderer tests keep passing. New callers can go through the
CitationStyle interface; ``works_cited`` remains the MLA source of truth.
"""

from __future__ import annotations

from app.renderers import works_cited
from app.renderers.styles.base import Run, SourceLike


class MLAStyle:
    key = "mla-9"
    edition = "MLA 9th (2021)"
    mechanism = "author_page"

    def required_fields(self, source_type: str) -> tuple[str, ...]:
        # MLA templates are keyed by the registry `kind`; source_type maps 1:1
        # here until the type-aware schema lands.
        return works_cited._REQUIRED.get(source_type, ())

    def format_reference(self, source: SourceLike, ordinal: int | None = None) -> list[Run]:
        return works_cited.format_entry(source.kind, source.fields)

    def sorted_entries(self, sources: list[SourceLike]) -> list[list[Run]]:
        return works_cited.sorted_entries(sources)


__all__ = ["MLAStyle"]
