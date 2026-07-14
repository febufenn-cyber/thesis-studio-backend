"""ASCE (American Society of Civil Engineers) — an author-date CitationStyle.

Used across civil-engineering scholarship. In-text is (Author year); the
reference list is alphabetical by author. Article/chapter titles are enclosed in
quotation marks while journal and book titles are italicised —
Author. (Year). "Article title." *Journal name*, volume(issue), pages. Like the
other author-date styles it uses the stored author string verbatim and reuses
the registry's required-field discipline so no bibliographic value is invented.
See docs/DOMAIN_EXPANSION.md.
"""

from __future__ import annotations

from app.renderers.styles.base import MissingCitationField, Run, SourceLike
from app.renderers.works_cited import _REQUIRED, _sort_key


def _require(fields: dict, kind: str) -> dict:
    desc = f"{kind}: {fields.get('title') or fields.get('author') or '?'}"
    if kind not in _REQUIRED:
        raise MissingCitationField("kind", f"unknown source kind {kind!r}")
    for field in _REQUIRED[kind]:
        value = str(fields.get(field, "")).strip()
        if not value or "[VERIFY]" in value:
            raise MissingCitationField(field, desc)
    return fields


class ASCEStyle:
    key = "asce"
    edition = "ASCE (current)"
    mechanism = "author_date"

    def required_fields(self, source_type: str) -> tuple[str, ...]:
        return _REQUIRED.get(source_type, ())

    def format_reference(self, source: SourceLike, ordinal: int | None = None) -> list[Run]:
        kind = source.kind
        f = _require(source.fields, kind)

        if kind in ("book", "translated_book"):
            runs = [Run(text=f"{f['author']}. ({f['year']}). ")]
            runs.append(Run(text=f["title"], italic=True))
            if kind == "translated_book":
                runs.append(Run(text=f". Translated by {f['translator']}, {f['publisher']}."))
            else:
                runs.append(Run(text=f". {f['publisher']}."))
            return runs
        if kind == "chapter_in_collection":
            return [
                Run(text=f"{f['author']}. ({f['year']}). \"{f['title']}.\" "),
                Run(text=f["container"], italic=True),
                Run(text=f", {f['editor']}, ed., {f['publisher']}, {f['pages']}."),
            ]
        if kind in ("journal", "journal_db"):
            runs = [
                Run(text=f"{f['author']}. ({f['year']}). \"{f['title']}.\" "),
                Run(text=f["container"], italic=True),
                Run(text=f", {f['volume']}({f['number']}), {f['pages']}."),
            ]
            if kind == "journal_db":
                runs.append(Run(text=f" {f['doi_or_url']}"))
            return runs
        if kind == "web":
            runs: list[Run] = []
            if f.get("author"):
                runs.append(Run(text=f"{f['author']}. "))
            date = f.get("pub_date") or "n.d."
            runs.append(Run(text=f"({date}). \"{f['title']}.\" "))
            runs.append(Run(text=f["site"], italic=True))
            runs.append(Run(text=f". {f['url']}."))
            return runs
        # film
        return [
            Run(text=f"{f['director']} (Director). ({f['year']}). "),
            Run(text=f["title"], italic=True),
            Run(text=f" [Film]. {f['studio']}."),
        ]

    def sorted_entries(self, sources: list[SourceLike]) -> list[list[Run]]:
        return [self.format_reference(source) for source in sorted(sources, key=_sort_key)]


__all__ = ["ASCEStyle"]
