"""BibTeX export for the citation registry.

Turns verified registry sources into a ``.bib`` string so a researcher can use
Acadensia's integrity-checked references directly in LaTeX/Overleaf. This is a
data-interchange serializer, not a citation *style*: it emits whatever fields are
present (BibTeX is lenient) without inventing values, and maps the registry
`kind` to a BibTeX entry type. First half of the AI-researcher I/O in
docs/DOMAIN_EXPANSION.md (a BibTeX importer is the complement).
"""

from __future__ import annotations

import re

from app.renderers.works_cited import SourceLike

# Registry kind -> BibTeX entry type.
_ENTRY_TYPE = {
    "book": "book",
    "translated_book": "book",
    "journal": "article",
    "journal_db": "article",
    "chapter_in_collection": "incollection",
    "web": "misc",
    "film": "misc",
}


def _cite_key(fields: dict, used: dict[str, int]) -> str:
    author = str(fields.get("author", "")).strip()
    surname = author.split(",")[0].strip() if author else str(fields.get("title", "")).strip()
    surname = re.sub(r"[^A-Za-z0-9]", "", surname) or "ref"
    year = re.sub(r"[^0-9]", "", str(fields.get("year", ""))) or "nd"
    base = f"{surname}{year}"
    # Disambiguate collisions: base, basea, baseb, ...
    n = used.get(base, 0)
    used[base] = n + 1
    return base if n == 0 else f"{base}{chr(ord('a') + n - 1)}"


def _escape(value: str) -> str:
    # Keep it simple and safe: strip the [VERIFY] marker and braces balancing.
    return str(value).replace("{", "").replace("}", "").strip()


def _entry(source: SourceLike, key: str) -> str:
    fields = source.fields
    kind = source.kind
    etype = _ENTRY_TYPE.get(kind, "misc")
    lines = [f"@{etype}{{{key},"]

    def add(bib_field: str, value) -> None:
        text = _escape(value) if value is not None else ""
        if text and "[VERIFY]" not in text:
            lines.append(f"  {bib_field} = {{{text}}},")

    add("author", fields.get("author"))
    add("title", fields.get("title"))
    add("year", fields.get("year"))
    if kind in ("journal", "journal_db"):
        add("journal", fields.get("container"))
        add("volume", fields.get("volume"))
        add("number", fields.get("number"))
        add("pages", fields.get("pages"))
        if kind == "journal_db":
            add("doi", fields.get("doi_or_url"))
    elif kind in ("book", "translated_book"):
        add("publisher", fields.get("publisher"))
        if kind == "translated_book":
            add("translator", fields.get("translator"))
    elif kind == "chapter_in_collection":
        add("booktitle", fields.get("container"))
        add("editor", fields.get("editor"))
        add("publisher", fields.get("publisher"))
        add("pages", fields.get("pages"))
    elif kind == "web":
        add("howpublished", fields.get("site"))
        add("url", fields.get("url"))
        add("urldate", fields.get("access_date"))
    elif kind == "film":
        add("author", fields.get("director"))
        add("howpublished", fields.get("studio"))

    lines.append("}")
    return "\n".join(lines)


def to_bibtex(sources: list[SourceLike]) -> str:
    """Serialize registry sources to a BibTeX string (order preserved)."""
    used: dict[str, int] = {}
    entries = [_entry(source, _cite_key(source.fields, used)) for source in sources]
    return ("\n\n".join(entries) + "\n") if entries else ""


__all__ = ["to_bibtex"]
