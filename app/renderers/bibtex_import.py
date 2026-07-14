"""BibTeX import for the citation registry.

Parses a ``.bib`` string into registry *source candidates* — the complement of
``app.renderers.bibtex`` (the exporter). Candidates feed the citation registry
as UNVERIFIED sources: we map only the fields BibTeX actually provides and never
invent missing bibliographic data (DESIGN.md rule 2). The verifier flags gaps
later. Second half of the AI-researcher I/O in docs/DOMAIN_EXPANSION.md.
"""

from __future__ import annotations

import re

# BibTeX entry type -> registry kind.
_KIND = {
    "article": "journal",
    "book": "book",
    "inbook": "chapter_in_collection",
    "incollection": "chapter_in_collection",
    "misc": "web",
    "online": "web",
    "electronic": "web",
    "inproceedings": "journal",
    "conference": "journal",
    "proceedings": "journal",
}

# BibTeX field -> registry field. Fields not listed are dropped (e.g. note).
_FIELD = {
    "author": "author",
    "title": "title",
    "year": "year",
    "publisher": "publisher",
    "journal": "container",
    "booktitle": "container",
    "volume": "volume",
    "number": "number",
    "issue": "number",
    "pages": "pages",
    "editor": "editor",
    "translator": "translator",
    "doi": "doi_or_url",
    "url": "url",
}

_SKIP_TYPES = {"comment", "string", "preamble"}


def _clean(value: str) -> str:
    """Strip one layer of surrounding braces/quotes and collapse whitespace."""
    text = value.strip()
    if len(text) >= 2 and (
        (text[0] == "{" and text[-1] == "}") or (text[0] == '"' and text[-1] == '"')
    ):
        text = text[1:-1]
    return re.sub(r"\s+", " ", text.replace("{", "").replace("}", "")).strip()


def _parse_fields(body: str) -> list[tuple[str, str]]:
    """Yield (name, raw_value) pairs from an entry body, in file order."""
    pairs: list[tuple[str, str]] = []
    i, n = 0, len(body)
    while i < n:
        while i < n and (body[i].isspace() or body[i] == ","):
            i += 1
        if i >= n:
            break
        start = i
        while i < n and body[i] != "=":
            i += 1
        name = body[start:i].strip().lower()
        if i >= n or not name:
            break
        i += 1  # skip '='
        while i < n and body[i].isspace():
            i += 1
        if i >= n:
            break
        if body[i] == "{":
            depth, vstart = 0, i
            while i < n:
                if body[i] == "{":
                    depth += 1
                elif body[i] == "}":
                    depth -= 1
                    if depth == 0:
                        i += 1
                        break
                i += 1
            raw = body[vstart:i]
        elif body[i] == '"':
            vstart = i
            i += 1
            while i < n and body[i] != '"':
                i += 1
            i += 1
            raw = body[vstart:i]
        else:  # bare value up to comma/end
            vstart = i
            while i < n and body[i] != ",":
                i += 1
            raw = body[vstart:i]
        pairs.append((name, raw))
    return pairs


def _parse_entries(text: str) -> list[tuple[str, str]]:
    """Return (entry_type, body) for each ``@type{...}`` block, in file order."""
    entries: list[tuple[str, str]] = []
    for m in re.finditer(r"@(\w+)\s*\{", text):
        etype = m.group(1).lower()
        i = m.end()
        depth, start = 1, i
        n = len(text)
        while i < n and depth:
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            i += 1
        body = text[start:i - 1] if depth == 0 else text[start:i]
        entries.append((etype, body))
    return entries


def from_bibtex(text: str) -> list[dict]:
    """Parse a BibTeX string into registry source candidates (file order).

    Each candidate is ``{"kind": <registry kind>, "fields": {<field>: <value>}}``.
    Only fields present in the source are mapped; nothing is invented. Entries
    with no recognizable fields (or @comment/@string/@preamble) are skipped.
    """
    candidates: list[dict] = []
    for etype, body in _parse_entries(text):
        if etype in _SKIP_TYPES:
            continue
        kind = _KIND.get(etype, "web")
        # The entry body is "citekey, field = val, ...". The cite key (no commas,
        # no '=') precedes the first comma; strip it so it is not merged into the
        # first field name.
        _, _, field_body = body.partition(",")
        raw = _parse_fields(field_body)
        if not raw:
            continue

        fields: dict[str, str] = {}
        seen_bib: dict[str, str] = {}
        for name, rawval in raw:
            seen_bib.setdefault(name, _clean(rawval))
            reg = _FIELD.get(name)
            if reg is None:
                continue
            value = _clean(rawval)
            if value and reg not in fields:
                fields[reg] = value

        if kind == "web":
            site = seen_bib.get("howpublished") or seen_bib.get("journal")
            if site and "site" not in fields:
                fields["site"] = site

        if kind == "journal" and fields.get("doi_or_url"):
            kind = "journal_db"
            fields.setdefault("database", "imported")

        if not fields:
            continue
        candidates.append({"kind": kind, "fields": fields})
    return candidates


__all__ = ["from_bibtex"]
