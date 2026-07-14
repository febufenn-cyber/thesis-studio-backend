"""CSL-JSON export for the citation registry.

Converts registry sources into CSL-JSON (Citation Style Language JSON), the
interchange format consumed by Zotero/citeproc and thousands of CSL styles.
Emitting this unlocks any CSL style without Acadensia implementing it. Like the
BibTeX exporter this is a data-interchange serializer, not a citation *style*: it
emits only fields that are present, never invents values, and skips unverified
"[VERIFY]" placeholders (DESIGN.md rule 2).
"""

from __future__ import annotations

import re

from app.renderers.works_cited import SourceLike

_CSL_TYPE = {
    "book": "book",
    "translated_book": "book",
    "journal": "article-journal",
    "journal_db": "article-journal",
    "chapter_in_collection": "chapter",
    "web": "webpage",
    "film": "motion_picture",
}

_DOI_RE = re.compile(r"10\.\d{4,9}/\S+")


def _clean(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if "[VERIFY]" in text else text


def _year(value) -> int | None:
    m = re.search(r"\d{4}", str(value or ""))
    return int(m.group()) if m else None


def _looks_like_doi(value: str) -> bool:
    return bool(_DOI_RE.search(value))


def _parse_authors(raw: str) -> list[dict]:
    parts = re.split(r"\s*;\s*|\s+and\s+", raw)
    names: list[dict] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if "," in part:
            family, _, given = part.partition(",")
            names.append({"family": family.strip(), "given": given.strip()})
        else:
            names.append({"literal": part})
    return names


def _stable_id(fields: dict, used: dict[str, int]) -> str:
    author = _clean(fields.get("author"))
    if author:
        first = re.split(r"\s*;\s*|\s+and\s+", author)[0]
        surname = first.split(",")[0].strip()
    else:
        surname = _clean(fields.get("title"))
    surname = re.sub(r"[^A-Za-z0-9]", "", surname) or "ref"
    year = _year(fields.get("year"))
    base = f"{surname}{year}" if year is not None else surname
    n = used.get(base, 0)
    used[base] = n + 1
    return base if n == 0 else f"{base}{chr(ord('a') + n - 1)}"


def _item(source: SourceLike, item_id: str) -> dict:
    fields = source.fields
    kind = source.kind
    item: dict = {"id": item_id, "type": _CSL_TYPE.get(kind, "document")}

    def put(csl_field: str, raw) -> None:
        text = _clean(raw)
        if text:
            item[csl_field] = text

    put("title", fields.get("title"))
    put("publisher", fields.get("publisher"))
    put("volume", fields.get("volume"))
    put("issue", fields.get("number"))
    put("page", fields.get("pages"))
    put("container-title", fields.get("container"))

    doi_or_url = _clean(fields.get("doi_or_url"))
    if doi_or_url:
        if kind == "journal_db" or _looks_like_doi(doi_or_url):
            item["DOI"] = doi_or_url
        else:
            item["URL"] = doi_or_url
    put("URL", fields.get("url"))

    editor = _clean(fields.get("editor"))
    if editor:
        item["editor"] = [{"literal": editor}]
    translator = _clean(fields.get("translator"))
    if translator:
        item["translator"] = [{"literal": translator}]

    author = _clean(fields.get("author"))
    authors = _parse_authors(author) if author else []
    if authors:
        item["author"] = authors

    year = _year(fields.get("year"))
    if year is not None:
        item["issued"] = {"date-parts": [[year]]}

    return item


def to_csl_json(sources: list) -> list[dict]:
    """Serialize registry sources to a list of CSL-JSON items (order preserved)."""
    used: dict[str, int] = {}
    return [_item(source, _stable_id(source.fields, used)) for source in sources]


__all__ = ["to_csl_json"]
