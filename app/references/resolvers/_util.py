"""Shared helpers for resolver adapters (author formatting, type mapping)."""

from __future__ import annotations

__all__ = ["authors_to_registry", "crossref_kind", "openalex_kind"]


def authors_to_registry(parts: list[dict]) -> str:
    """Join a list of ``{"family","given"}`` author objects into registry form.

    Registry ``author`` fields use ``Family, Given and Family, Given`` (matching
    the BibTeX importer and Works Cited parser). Entries missing a family name
    are skipped rather than guessed.
    """
    names: list[str] = []
    for person in parts:
        family = (person.get("family") or person.get("last") or "").strip()
        given = (person.get("given") or person.get("first") or "").strip()
        if not family and not given:
            literal = (person.get("name") or person.get("literal") or "").strip()
            if literal:
                names.append(literal)
            continue
        if family and given:
            names.append(f"{family}, {given}")
        elif family:
            names.append(family)
    return " and ".join(names)


_CROSSREF_KIND = {
    "journal-article": "journal",
    "proceedings-article": "journal",
    "book": "book",
    "monograph": "book",
    "reference-book": "book",
    "book-chapter": "chapter_in_collection",
    "book-section": "chapter_in_collection",
}


def crossref_kind(crossref_type: str) -> str:
    return _CROSSREF_KIND.get(crossref_type, "web")


_OPENALEX_KIND = {
    "article": "journal",
    "journal-article": "journal",
    "proceedings-article": "journal",
    "book": "book",
    "monograph": "book",
    "book-chapter": "chapter_in_collection",
}


def openalex_kind(openalex_type: str) -> str:
    return _OPENALEX_KIND.get(openalex_type, "web")
