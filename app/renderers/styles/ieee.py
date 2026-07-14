"""IEEE 2021 reference style — the second CitationStyle family (numbered).

Proves the interface spans mechanisms: unlike MLA (author-page, alphabetical),
IEEE numbers references [n] in order of appearance. Reuses the registry's
required-field discipline (never guess a bibliographic value) but renders the
IEEE structure: author, "title," *container*, vol./no., pp., year. Author-name
reformatting (F. M. Last) is deliberately out of scope for this foundation; the
stored author string is used verbatim. See docs/DOMAIN_EXPANSION.md.
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


class IEEEStyle:
    key = "ieee-2021"
    edition = "IEEE (2021 reference guide)"
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
            tail = f". {f['publisher']}, {f['year']}."
            if kind == "translated_book":
                tail = f", Transl. {f['translator']}. {f['publisher']}, {f['year']}."
            runs.append(Run(text=tail))
            return runs
        if kind == "chapter_in_collection":
            return [
                Run(text=f"{prefix}{f['author']}, “{f['title']},” in "),
                Run(text=f["container"], italic=True),
                Run(text=f", {f['editor']}, Ed. {f['publisher']}, {f['year']}, pp. {f['pages']}."),
            ]
        if kind in ("journal", "journal_db"):
            runs = [
                Run(text=f"{prefix}{f['author']}, “{f['title']},” "),
                Run(text=f["container"], italic=True),
                Run(text=f", vol. {f['volume']}, no. {f['number']}, pp. {f['pages']}, {f['year']}."),
            ]
            if kind == "journal_db":
                runs.append(Run(text=f" doi: {f['doi_or_url']}."))
            return runs
        if kind == "web":
            runs = [Run(text=prefix)]
            if f.get("author"):
                runs.append(Run(text=f"{f['author']}, "))
            runs.append(Run(text=f"“{f['title']},” "))
            runs.append(Run(text=f["site"], italic=True))
            runs.append(Run(text=f". [Online]. Available: {f['url']}"))
            if f.get("access_date"):
                runs.append(Run(text=f" (accessed {f['access_date']})."))
            return runs
        # film
        return [
            Run(text=f"{prefix}"),
            Run(text=f["title"], italic=True),
            Run(text=f". Dir. {f['director']}. {f['studio']}, {f['year']}."),
        ]

    def sorted_entries(self, sources: list[SourceLike]) -> list[list[Run]]:
        # Numbered styles list references in order of appearance, numbered [1..n].
        return [self.format_reference(source, ordinal=i + 1) for i, source in enumerate(sources)]


__all__ = ["IEEEStyle"]
