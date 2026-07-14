"""AIP (current) reference style — a NUMBERED-family CitationStyle.

Follows the American Institute of Physics reference format used across physics:
numbered references in order of appearance, with the compact AIP journal form
``Author, Journal (italic) Volume, Pages (Year).`` The stored author string is
used verbatim (author-name reformatting is out of scope, as with IEEE), and only
``italic`` emphasis is available on the canonical Run. Missing required fields
raise MissingCitationField — bibliographic data is never guessed.
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


class AIPStyle:
    key = "aip"
    edition = "AIP (current)"
    mechanism = "numbered"

    def required_fields(self, source_type: str) -> tuple[str, ...]:
        return _REQUIRED.get(source_type, ())

    def format_reference(self, source: SourceLike, ordinal: int | None = None) -> list[Run]:
        kind = source.kind
        f = _require(source.fields, kind)
        prefix = f"[{ordinal}] " if ordinal is not None else ""

        if kind in ("book", "translated_book"):
            runs = [Run(text=f"{prefix}{f['author']}, ")]
            runs.append(Run(text=f["title"], italic=True))
            if kind == "translated_book":
                runs.append(
                    Run(text=f", translated by {f['translator']} ({f['publisher']}, {f['year']}).")
                )
            else:
                runs.append(Run(text=f" ({f['publisher']}, {f['year']})."))
            return runs
        if kind == "chapter_in_collection":
            return [
                Run(text=f'{prefix}{f["author"]}, "{f["title"]}," in '),
                Run(text=f["container"], italic=True),
                Run(text=(
                    f", edited by {f['editor']} ({f['publisher']}, {f['year']}),"
                    f" pp. {f['pages']}."
                )),
            ]
        if kind in ("journal", "journal_db"):
            runs = [
                Run(text=f"{prefix}{f['author']}, "),
                Run(text=f["container"], italic=True),
                Run(text=f" {f['volume']}, {f['pages']} ({f['year']})."),
            ]
            if kind == "journal_db":
                runs.append(Run(text=f" doi: {f['doi_or_url']}."))
            return runs
        if kind == "web":
            runs = [Run(text=prefix)]
            if f.get("author"):
                runs.append(Run(text=f"{f['author']}, "))
            runs.append(Run(text=f'"{f["title"]}," '))
            runs.append(Run(text=f["site"], italic=True))
            runs.append(Run(text=f", {f['url']}"))
            if f.get("access_date"):
                runs.append(Run(text=f" (accessed {f['access_date']})."))
            else:
                runs.append(Run(text="."))
            return runs
        # film
        return [
            Run(text=prefix),
            Run(text=f["title"], italic=True),
            Run(text=f", directed by {f['director']} ({f['studio']}, {f['year']})."),
        ]

    def sorted_entries(self, sources: list[SourceLike]) -> list[list[Run]]:
        return [self.format_reference(source, ordinal=i + 1) for i, source in enumerate(sources)]


__all__ = ["AIPStyle"]
