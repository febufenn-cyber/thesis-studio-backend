"""CSL-JSON import — inverse of app/renderers/csl.

Maps CSL-JSON items into registry source candidates ``{"kind", "fields"}``,
mapping only fields present in the item (never invents data). The complement of
``to_csl_json`` for Zotero/citeproc round-tripping.
"""

from __future__ import annotations

import json

__all__ = ["from_csl_json"]

_CSL_TO_KIND = {
    "book": "book",
    "chapter": "chapter_in_collection",
    "article-journal": "journal",
    "article": "journal",
    "paper-conference": "journal",
    "webpage": "web",
    "motion_picture": "film",
}


def _authors_to_registry(people: list) -> str:
    names: list[str] = []
    for person in people or []:
        if not isinstance(person, dict):
            continue
        family = str(person.get("family", "")).strip()
        given = str(person.get("given", "")).strip()
        literal = str(person.get("literal", "")).strip()
        if family and given:
            names.append(f"{family}, {given}")
        elif family:
            names.append(family)
        elif literal:
            names.append(literal)
    return " and ".join(names)


def _year(issued: dict) -> str:
    try:
        return str(issued["date-parts"][0][0])
    except (KeyError, IndexError, TypeError):
        return ""


def _item_to_candidate(item: dict) -> dict | None:
    if not isinstance(item, dict):
        return None
    kind = _CSL_TO_KIND.get(str(item.get("type", "")), "web")
    fields: dict[str, str] = {}

    def put(field: str, value) -> None:
        text = str(value or "").strip()
        if text:
            fields[field] = text

    put("title", item.get("title"))
    put("publisher", item.get("publisher"))
    put("container", item.get("container-title"))
    put("volume", item.get("volume"))
    put("number", item.get("issue"))
    put("pages", item.get("page"))
    put("doi_or_url", item.get("DOI"))
    if not fields.get("doi_or_url"):
        put("url", item.get("URL"))
    author = _authors_to_registry(item.get("author") or [])
    if author:
        fields["author"] = author
    editor = _authors_to_registry(item.get("editor") or [])
    if editor:
        fields["editor"] = editor
    year = _year(item.get("issued") or {})
    if year:
        fields["year"] = year

    if not fields:
        return None
    return {"kind": kind, "fields": fields}


def from_csl_json(content: str) -> list[dict]:
    """Parse a CSL-JSON string (array of items) into source candidates."""
    try:
        data = json.loads(content)
    except (ValueError, TypeError):
        return []
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return []
    candidates: list[dict] = []
    for item in data:
        candidate = _item_to_candidate(item)
        if candidate is not None:
            candidates.append(candidate)
    return candidates
