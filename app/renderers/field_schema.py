"""Type-aware citation field schema (style-agnostic validation surface).

Derives required fields from the MLA Works Cited templates
(``works_cited._REQUIRED``) and pairs them with a per-kind optional-field map
plus the style-agnostic ``source_type`` (``source_types.source_type_for_kind``).

The ``missing_required`` helper is the never-guess validation surface (DESIGN.md
rule 2): a required field that is absent, blank, or still marked ``[VERIFY]`` is
reported as missing regardless of citation style.
"""

from __future__ import annotations

from app.renderers.source_types import source_type_for_kind
from app.renderers.works_cited import _REQUIRED

__all__ = [
    "REQUIRED_FIELDS",
    "OPTIONAL_FIELDS",
    "field_schema_for_kind",
    "missing_required",
    "all_kinds",
]


REQUIRED_FIELDS: dict[str, tuple[str, ...]] = dict(_REQUIRED)

OPTIONAL_FIELDS: dict[str, tuple[str, ...]] = {
    "book": ("edition", "doi_or_url"),
    "translated_book": ("edition", "doi_or_url"),
    "chapter_in_collection": ("volume", "edition", "doi_or_url"),
    "journal": ("doi_or_url",),
    "journal_db": ("access_date",),
    "web": ("author", "pub_date", "access_date"),
    "film": ("performers", "medium"),
}


def _is_missing(value: object) -> bool:
    text = str(value if value is not None else "").strip()
    return not text or "[VERIFY]" in text


def field_schema_for_kind(kind: str) -> dict:
    """Return {"kind", "source_type", "required", "optional"} for a registry kind."""
    return {
        "kind": kind,
        "source_type": source_type_for_kind(kind),
        "required": list(REQUIRED_FIELDS.get(kind, ())),
        "optional": list(OPTIONAL_FIELDS.get(kind, ())),
    }


def missing_required(kind: str, fields: dict) -> list[str]:
    """Required field names absent/empty/``[VERIFY]`` in ``fields`` (never-guess)."""
    return [name for name in REQUIRED_FIELDS.get(kind, ()) if _is_missing(fields.get(name))]


def all_kinds() -> list[str]:
    """All registry kinds that can produce a formatted Works Cited entry."""
    return list(REQUIRED_FIELDS)
