"""Map registry citation `kind` values to style-agnostic source types.

Pure, dependency-free helper. `kind` is the MLA template key used by the
Works Cited renderer; `source_type` is the style-agnostic classification
stored on the Source model (see docs/DOMAIN_EXPANSION.md).
"""

from __future__ import annotations

__all__ = ["source_type_for_kind"]


_KIND_TO_SOURCE_TYPE: dict[str, str] = {
    "book": "book",
    "translated_book": "book",
    "journal": "article",
    "journal_db": "article",
    "chapter_in_collection": "chapter",
    "web": "webpage",
    "film": "film",
}


def source_type_for_kind(kind: str) -> str:
    """Return the style-agnostic source_type for a registry `kind`.

    Unknown kinds fall back to "other".
    """
    return _KIND_TO_SOURCE_TYPE.get(kind, "other")
