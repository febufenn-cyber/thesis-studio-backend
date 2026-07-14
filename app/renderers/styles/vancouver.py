"""Vancouver / ICMJE reference style — a numbered family for medicine/health.

Like IEEE, Vancouver numbers references in order of appearance ([n]) rather than
alphabetising them, but it follows the ICMJE recommendations widely used in
medicine, nursing, and the health sciences: author list, then article/chapter
title, then the (abbreviated) source, with year;volume(issue):pages for journals.
Reuses the registry's required-field discipline (never guess a bibliographic
value); the stored author string is used verbatim (no F. M. Last reformatting).
See docs/DOMAIN_EXPANSION.md.
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


class VancouverStyle:
    key = "vancouver-icmje"
    edition = "Vancouver / ICMJE (current)"
    mechanism = "numbered"

    def required_fields(self, source_type: str) -> tuple[str, ...]:
        return _REQUIRED.get(source_type, ())

    def format_reference(self, source: SourceLike, ordinal: int | None = None) -> list[Run]:
        kind = source.kind
        f = _require(source.fields, kind)
        prefix = f"[{ordinal}] " if ordinal is not None else ""

        if kind in ("book", "translated_book"):
            runs = [Run(text=f"{prefix}{f['author']}. ")]
            runs.append(Run(text=f["title"], italic=True))
            if kind == "translated_book":
                runs.append(Run(text=f". Translated by {f['translator']}. {f['publisher']}; {f['year']}."))
            else:
                runs.append(Run(text=f". {f['publisher']}; {f['year']}."))
            return runs
        if kind == "chapter_in_collection":
            return [
                Run(text=f"{prefix}{f['author']}. {f['title']}. In: {f['editor']}, editor. "),
                Run(text=f["container"], italic=True),
                Run(text=f". {f['publisher']}; {f['year']}. p. {f['pages']}."),
            ]
        if kind in ("journal", "journal_db"):
            runs = [
                Run(text=f"{prefix}{f['author']}. {f['title']}. "),
                Run(text=f["container"], italic=True),
                Run(text=f". {f['year']};{f['volume']}({f['number']}):{f['pages']}."),
            ]
            if kind == "journal_db":
                runs.append(Run(text=f" doi: {f['doi_or_url']}."))
            return runs
        if kind == "web":
            runs = [Run(text=prefix)]
            if f.get("author"):
                runs.append(Run(text=f"{f['author']}. "))
            runs.append(Run(text=f"{f['title']} [Internet]. "))
            runs.append(Run(text=f["site"], italic=True))
            if f.get("access_date"):
                runs.append(Run(text=f"; [cited {f['access_date']}]. Available from: {f['url']}"))
            else:
                runs.append(Run(text=f". Available from: {f['url']}"))
            return runs
        # film
        return [
            Run(text=prefix),
            Run(text=f["title"], italic=True),
            Run(text=f" [film]. Directed by {f['director']}. {f['studio']}; {f['year']}."),
        ]

    def sorted_entries(self, sources: list[SourceLike]) -> list[list[Run]]:
        return [self.format_reference(source, ordinal=i + 1) for i, source in enumerate(sources)]


__all__ = ["VancouverStyle"]
