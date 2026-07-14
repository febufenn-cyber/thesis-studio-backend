"""ACS (2020 Guide) reference style — a NUMBERED-family CitationStyle.

Follows the ACS Guide to Scholarly Communication reference format used in
chemistry: numbered references in order of appearance, author string then
title, then the abbreviated journal name (italic), year, volume (italic) and
pages, with a DOI when the source carries one. ACS renders the journal title
and volume in bold in print; Acadensia's canonical Run only exposes ``italic``
for emphasis, so italic stands in for that emphasis here. As with IEEE,
author-name reformatting is out of scope — the stored author string is used
verbatim. Missing required fields raise MissingCitationField (never guessed).
"""

from __future__ import annotations

from app.renderers.styles.base import MissingCitationField, Run, SourceLike
from app.renderers.works_cited import _REQUIRED


def _require(fields: dict, kind: str) -> dict:
    desc = f"{kind}: {fields.get('title') or fields.get('author') or '?'}"
    if kind not in _REQUIRED:
        raise MissingCitationField("kind", f"unknown source kind {kind!r}")
    for field in _REQUIRED[kind]:
        value = str(fields.get(field, "")).strip()
        if not value or "[VERIFY]" in value:
            raise MissingCitationField(field, desc)
    return fields


class ACSStyle:
    key = "acs-2020"
    edition = "ACS (2020 Guide)"
    mechanism = "numbered"

    def required_fields(self, source_type: str) -> tuple[str, ...]:
        return _REQUIRED.get(source_type, ())

    def format_reference(self, source: SourceLike, ordinal: int | None = None) -> list[Run]:
        kind = source.kind
        f = _require(source.fields, kind)
        prefix = f"[{ordinal}] " if ordinal is not None else ""

        if kind in ("book", "translated_book"):
            runs = [Run(text=f"{prefix}{f['author']} ")]
            runs.append(Run(text=f["title"], italic=True))
            if kind == "translated_book":
                runs.append(
                    Run(text=f"; Translated by {f['translator']}; {f['publisher']}: {f['year']}.")
                )
            else:
                runs.append(Run(text=f"; {f['publisher']}: {f['year']}."))
            return runs
        if kind == "chapter_in_collection":
            return [
                Run(text=f"{prefix}{f['author']} {f['title']}. In "),
                Run(text=f["container"], italic=True),
                Run(text=f"; {f['editor']}, Ed.; {f['publisher']}: {f['year']}; pp {f['pages']}."),
            ]
        if kind in ("journal", "journal_db"):
            runs = [
                Run(text=f"{prefix}{f['author']} {f['title']}. "),
                Run(text=f["container"], italic=True),
                Run(text=f" {f['year']}, "),
                Run(text=str(f["volume"]), italic=True),
                Run(text=f", {f['pages']}."),
            ]
            if kind == "journal_db":
                runs.append(Run(text=f" DOI: {f['doi_or_url']}."))
            return runs
        if kind == "web":
            runs = [Run(text=prefix)]
            if f.get("author"):
                runs.append(Run(text=f"{f['author']} "))
            runs.append(Run(text=f"{f['title']}. "))
            runs.append(Run(text=f["site"], italic=True))
            runs.append(Run(text=f". {f['url']}"))
            if f.get("access_date"):
                runs.append(Run(text=f" (accessed {f['access_date']})."))
            else:
                runs.append(Run(text="."))
            return runs
        # film
        return [
            Run(text=prefix),
            Run(text=f["title"], italic=True),
            Run(text=f"; {f['director']}; {f['studio']}, {f['year']}."),
        ]

    def sorted_entries(self, sources: list[SourceLike]) -> list[list[Run]]:
        return [self.format_reference(source, ordinal=i + 1) for i, source in enumerate(sources)]


__all__ = ["ACSStyle"]
