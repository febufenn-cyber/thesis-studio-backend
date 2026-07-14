"""AMA 11th edition reference style — a third numbered CitationStyle.

AMA (American Medical Association Manual of Style, 11th ed., 2020) is the house
style of JAMA and most AMA/medical journals. Like IEEE it belongs to the
*numbered* mechanism family: in-text citations are superscript numerals and the
reference list is numbered in order of appearance. Structure differs from IEEE:
authors, then article/chapter title (roman), then the abbreviated journal name
(italic), then ``Year;Volume(Issue):Pages`` and a ``doi:`` when present. Book and
website *titles* are italic; article titles are not.

Reuses the registry's required-field discipline (never guess a bibliographic
value); the stored author string is used verbatim (AMA "Last FM" reformatting is
out of scope). See docs/DOMAIN_EXPANSION.md.
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


class AMAStyle:
    key = "ama-11"
    edition = "AMA 11th (2020)"
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
                runs.append(Run(text=f". {f['translator']}, trans. {f['publisher']}; {f['year']}."))
            else:
                runs.append(Run(text=f". {f['publisher']}; {f['year']}."))
            return runs
        if kind == "chapter_in_collection":
            return [
                Run(text=f"{prefix}{f['author']}. {f['title']}. In: {f['editor']}, ed. "),
                Run(text=f["container"], italic=True),
                Run(text=f". {f['publisher']}; {f['year']}:{f['pages']}."),
            ]
        if kind in ("journal", "journal_db"):
            runs = [
                Run(text=f"{prefix}{f['author']}. {f['title']}. "),
                Run(text=f["container"], italic=True),
                Run(text=f". {f['year']};{f['volume']}({f['number']}):{f['pages']}."),
            ]
            if kind == "journal_db":
                runs.append(Run(text=f" doi:{f['doi_or_url']}"))
            return runs
        if kind == "web":
            runs = [Run(text=prefix)]
            if f.get("author"):
                runs.append(Run(text=f"{f['author']}. "))
            runs.append(Run(text=f"{f['title']}. "))
            runs.append(Run(text=f["site"], italic=True))
            if f.get("access_date"):
                runs.append(Run(text=f". Accessed {f['access_date']}. {f['url']}"))
            else:
                runs.append(Run(text=f". {f['url']}"))
            return runs
        # film
        return [
            Run(text=prefix),
            Run(text=f["title"], italic=True),
            Run(text=f". Directed by {f['director']}. {f['studio']}; {f['year']}."),
        ]

    def sorted_entries(self, sources: list[SourceLike]) -> list[list[Run]]:
        return [self.format_reference(source, ordinal=i + 1) for i, source in enumerate(sources)]


__all__ = ["AMAStyle"]
