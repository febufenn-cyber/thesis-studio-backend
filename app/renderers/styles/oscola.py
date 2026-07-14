"""OSCOLA (4th ed.) — UK/Commonwealth legal citation as a notes CitationStyle.

OSCOLA (Oxford Standard for the Citation of Legal Authorities) is the standard
UK/Commonwealth legal system. Like Chicago Notes-Bibliography it is a notes
mechanism: a numbered stream of FOOTNOTES (assembled by
``notes_engine.build_notes``) plus an alphabetical BIBLIOGRAPHY
(``sorted_entries``).

SCOPE: The registry models only SECONDARY sources — book, translated_book,
chapter_in_collection, journal, journal_db, web, film. This module implements
OSCOLA formatting for those secondary-source kinds only. PRIMARY legal
authorities (cases, statutes) require new registry kinds and dedicated rules
(neutral citations, law reports, sections) and are OUT OF SCOPE here.

Formatting notes: OSCOLA italicises book and journal titles and puts article /
chapter titles in single quotation marks; footnotes carry no closing full stop.
Only italic is available on ``Run``, which suffices for OSCOLA's title styling.
The stored author string is used verbatim and the registry's required-field
discipline is reused via ``_require`` so no bibliographic value is invented.
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


def _last_name(name: str) -> str:
    name = name.strip()
    if not name:
        return name
    if "," in name:
        return name.split(",")[0].strip()
    return name.split()[-1]


class OSCOLAStyle:
    key = "oscola-4"
    edition = "OSCOLA (4th)"
    mechanism = "notes"

    def required_fields(self, source_type: str) -> tuple[str, ...]:
        return _REQUIRED.get(source_type, ())

    def _full(self, kind: str, f: dict) -> list[Run]:
        if kind in ("book", "translated_book"):
            runs = [Run(text=f"{f['author']}, "), Run(text=f["title"], italic=True)]
            if kind == "translated_book":
                runs.append(Run(text=f" (tr {f['translator']}, {f['publisher']} {f['year']})"))
            else:
                runs.append(Run(text=f" ({f['publisher']} {f['year']})"))
            return runs
        if kind == "chapter_in_collection":
            return [
                Run(text=f"{f['author']}, '{f['title']}' in {f['editor']} (ed), "),
                Run(text=f["container"], italic=True),
                Run(text=f" ({f['publisher']} {f['year']}) {f['pages']}"),
            ]
        if kind in ("journal", "journal_db"):
            runs = [
                Run(text=f"{f['author']}, '{f['title']}' ({f['year']}) {f['volume']} "),
                Run(text=f["container"], italic=True),
                Run(text=f" {f['pages']}"),
            ]
            if kind == "journal_db":
                runs.append(Run(text=f" <{f['doi_or_url']}>"))
            return runs
        if kind == "web":
            runs: list[Run] = []
            if f.get("author"):
                runs.append(Run(text=f"{f['author']}, "))
            runs.append(Run(text=f"'{f['title']}' ({f['site']}) <{f['url']}>"))
            return runs
        # film
        return [
            Run(text=f["title"], italic=True),
            Run(text=f" ({f['director']}, {f['studio']} {f['year']})"),
        ]

    def format_reference(self, source: SourceLike, ordinal: int | None = None) -> list[Run]:
        kind = source.kind
        return self._full(kind, _require(source.fields, kind))

    def sorted_entries(self, sources: list[SourceLike]) -> list[list[Run]]:
        return [self.format_reference(source) for source in sorted(sources, key=_sort_key)]

    def format_note(self, source: SourceLike, first: bool = True) -> list[Run]:
        kind = source.kind
        f = _require(source.fields, kind)
        if first:
            return self._full(kind, f)
        return self._short(kind, f)

    def _short(self, kind: str, f: dict) -> list[Run]:
        last = _last_name(f.get("author") or f.get("director") or "")
        lead = f"{last}, " if last else ""
        if kind in ("book", "translated_book"):
            return [Run(text=lead), Run(text=f["title"], italic=True)]
        if kind in ("journal", "journal_db", "chapter_in_collection"):
            return [Run(text=f"{lead}'{f['title']}' {f['pages']}")]
        if kind == "web":
            return [Run(text=f"{lead}'{f['title']}'")]
        # film
        return [Run(text=f["title"], italic=True)]


__all__ = ["OSCOLAStyle"]
