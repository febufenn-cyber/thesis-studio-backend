"""RIS import/export for the citation registry.

RIS is the tag-based interchange format read/written by Zotero, EndNote and
Mendeley: one ``TAG  - value`` per line, each record opening with ``TY`` and
closing with ``ER``. Like the BibTeX serializer this is a data-interchange
layer, not a citation *style*: it emits only the fields that are present and
never invents bibliographic data (DESIGN.md rule 2), mapping the registry
`kind` to an RIS reference type. Complement of ``bibtex.py`` for AI-researcher
I/O (docs/DOMAIN_EXPANSION.md).
"""

from __future__ import annotations

from app.renderers.works_cited import SourceLike

# Registry kind -> RIS reference type (TY).
_TY = {
    "book": "BOOK",
    "translated_book": "BOOK",
    "chapter_in_collection": "CHAP",
    "journal": "JOUR",
    "journal_db": "JOUR",
    "web": "ELEC",
    "film": "VIDEO",
}

# Reverse: RIS type -> registry kind.
_KIND = {
    "BOOK": "book",
    "CHAP": "chapter_in_collection",
    "JOUR": "journal",
    "ELEC": "web",
    "VIDEO": "film",
}


def _clean(value) -> str:
    return str(value).strip() if value is not None else ""


def _add_pages(lines: list[str], pages) -> None:
    text = _clean(pages)
    if not text or "[VERIFY]" in text:
        return
    if "-" in text:
        start, _, end = text.partition("-")
        start, end = start.strip(), end.strip()
        if start:
            lines.append(f"SP  - {start}")
        if end:
            lines.append(f"EP  - {end}")
    else:
        lines.append(f"SP  - {text}")


def _record(source: SourceLike) -> list[str]:
    fields = source.fields
    kind = source.kind
    ty = _TY.get(kind, "GEN")
    lines = [f"TY  - {ty}"]

    def add(tag: str, value) -> None:
        text = _clean(value)
        if text and "[VERIFY]" not in text:
            lines.append(f"{tag}  - {text}")

    add("AU", fields.get("author"))
    add("TI", fields.get("title"))
    add("PY", fields.get("year"))

    if kind in ("journal", "journal_db"):
        add("JO", fields.get("container"))
        add("VL", fields.get("volume"))
        add("IS", fields.get("number"))
        _add_pages(lines, fields.get("pages"))
        if kind == "journal_db":
            add("DO", fields.get("doi_or_url"))
    elif kind in ("book", "translated_book"):
        add("PB", fields.get("publisher"))
    elif kind == "chapter_in_collection":
        add("T2", fields.get("container"))
        add("ED", fields.get("editor"))
        add("PB", fields.get("publisher"))
        _add_pages(lines, fields.get("pages"))
    elif kind == "web":
        add("UR", fields.get("url"))
    elif kind == "film":
        add("PB", fields.get("studio"))

    lines.append("ER  - ")
    return lines


def to_ris(sources: list[SourceLike]) -> str:
    """Serialize registry sources to an RIS string (order preserved)."""
    blocks = ["\n".join(_record(s)) for s in sources]
    return ("\n\n".join(blocks) + "\n") if blocks else ""


# RIS tag -> registry field name (single-value fields).
_TAG_FIELD = {
    "AU": "author",
    "TI": "title",
    "PY": "year",
    "JO": "container",
    "JF": "container",
    "T2": "container",
    "VL": "volume",
    "IS": "number",
    "PB": "publisher",
    "DO": "doi_or_url",
    "UR": "url",
    "ED": "editor",
}


def from_ris(text: str) -> list[dict]:
    """Parse RIS text into registry candidates [{"kind":..., "fields":{...}}]."""
    candidates: list[dict] = []
    ty: str | None = None
    fields: dict[str, str] = {}
    sp = ep = None

    def flush() -> None:
        nonlocal ty, fields, sp, ep
        if ty is not None:
            if sp is not None and ep is not None:
                fields["pages"] = f"{sp}-{ep}"
            elif sp is not None:
                fields["pages"] = sp
            candidates.append({"kind": _KIND.get(ty, "book"), "fields": fields})
        ty, fields, sp, ep = None, {}, None, None

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if len(line) >= 2 and line[:2].isalpha() and "-" in line[2:]:
            tag = line[:2].upper()
            value = line[2:].split("-", 1)[1].strip()
        else:
            continue

        if tag == "TY":
            flush()
            ty = value.upper()
        elif tag == "ER":
            flush()
        elif ty is None:
            continue
        elif tag == "SP":
            sp = value
        elif tag == "EP":
            ep = value
        elif tag in _TAG_FIELD and value:
            fields[_TAG_FIELD[tag]] = value

    flush()
    return candidates


__all__ = ["to_ris", "from_ris"]
