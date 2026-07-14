"""APA 7th edition — the author-date CitationStyle family.

Covers social sciences (psychology, education, business, communications). In-text
is (Author, Year); the reference list is alphabetical by author. Like the other
foundation styles it uses the stored author string verbatim (APA name inversion
is a later refinement) and reuses the registry's required-field discipline so no
bibliographic value is invented. See docs/DOMAIN_EXPANSION.md.
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


class APAStyle:
    key = "apa-7"
    edition = "APA 7th (2020)"
    mechanism = "author_date"

    def required_fields(self, source_type: str) -> tuple[str, ...]:
        return _REQUIRED.get(source_type, ())

    def format_reference(self, source: SourceLike, ordinal: int | None = None) -> list[Run]:
        kind = source.kind
        f = _require(source.fields, kind)

        if kind in ("book", "translated_book"):
            runs = [Run(text=f"{f['author']} ({f['year']}). ")]
            runs.append(Run(text=f["title"], italic=True))
            if kind == "translated_book":
                runs.append(Run(text=f" (Trans. {f['translator']}). {f['publisher']}."))
            else:
                runs.append(Run(text=f". {f['publisher']}."))
            return runs
        if kind == "chapter_in_collection":
            return [
                Run(text=f"{f['author']} ({f['year']}). {f['title']}. In {f['editor']} (Ed.), "),
                Run(text=f["container"], italic=True),
                Run(text=f" (pp. {f['pages']}). {f['publisher']}."),
            ]
        if kind in ("journal", "journal_db"):
            runs = [
                Run(text=f"{f['author']} ({f['year']}). {f['title']}. "),
                Run(text=f["container"], italic=True),
                Run(text=f", {f['volume']}({f['number']}), {f['pages']}."),
            ]
            if kind == "journal_db":
                runs.append(Run(text=f" {f['doi_or_url']}"))
            return runs
        if kind == "web":
            runs: list[Run] = []
            if f.get("author"):
                runs.append(Run(text=f"{f['author']} "))
            date = f.get("pub_date") or "n.d."
            runs.append(Run(text=f"({date}). {f['title']}. "))
            runs.append(Run(text=f["site"], italic=True))
            runs.append(Run(text=f". {f['url']}"))
            return runs
        # film
        return [
            Run(text=f"{f['director']} (Director). ({f['year']}). "),
            Run(text=f["title"], italic=True),
            Run(text=f" [Film]. {f['studio']}."),
        ]

    def sorted_entries(self, sources: list[SourceLike]) -> list[list[Run]]:
        # Author-date: alphabetical by author surname (no order-of-appearance).
        return [self.format_reference(source) for source in sorted(sources, key=_sort_key)]


__all__ = ["APAStyle"]
