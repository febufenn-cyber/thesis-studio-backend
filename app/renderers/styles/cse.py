"""CSE 8th edition, Name-Year system — an author-date CitationStyle.

Council of Science Editors, used across biology and the life sciences. The
Name-Year variant places the year immediately after the author, keeps the
reference list alphabetical by author, and uses minimal punctuation with
(commonly abbreviated) journal titles. Unlike MLA/APA, CSE does NOT italicize
titles, so every run is plain text. Like the other foundation styles it uses the
stored author string verbatim and reuses the registry's required-field
discipline so no bibliographic value is invented. See docs/DOMAIN_EXPANSION.md.
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


class CSEStyle:
    key = "cse-8-nameyear"
    edition = "CSE 8th (Name-Year)"
    mechanism = "author_date"

    def required_fields(self, source_type: str) -> tuple[str, ...]:
        return _REQUIRED.get(source_type, ())

    def format_reference(self, source: SourceLike, ordinal: int | None = None) -> list[Run]:
        kind = source.kind
        f = _require(source.fields, kind)

        # CSE Name-Year: author. Year. Title. Source details. No italic titles.
        if kind == "book":
            return [Run(text=f"{f['author']}. {f['year']}. {f['title']}. {f['publisher']}.")]
        if kind == "translated_book":
            return [Run(text=(
                f"{f['author']}. {f['year']}. {f['title']}. "
                f"{f['translator']}, translator. {f['publisher']}."
            ))]
        if kind == "chapter_in_collection":
            return [Run(text=(
                f"{f['author']}. {f['year']}. {f['title']}. "
                f"In: {f['editor']}, editor. {f['container']}. "
                f"{f['publisher']}. p. {f['pages']}."
            ))]
        if kind in ("journal", "journal_db"):
            text = (
                f"{f['author']}. {f['year']}. {f['title']}. "
                f"{f['container']}. {f['volume']}({f['number']}):{f['pages']}."
            )
            if kind == "journal_db":
                text += f" {f['doi_or_url']}"
            return [Run(text=text)]
        if kind == "web":
            parts: list[str] = []
            if f.get("author"):
                parts.append(f"{f['author']}.")
            date = f.get("pub_date") or "[date unknown]"
            parts.append(f"{date}.")
            parts.append(f"{f['title']} [Internet].")
            parts.append(f"{f['site']}.")
            parts.append(f"Available from: {f['url']}")
            return [Run(text=" ".join(parts))]
        # film
        return [Run(text=(
            f"{f['director']}, director. {f['year']}. "
            f"{f['title']} [film]. {f['studio']}."
        ))]

    def sorted_entries(self, sources: list[SourceLike]) -> list[list[Run]]:
        return [self.format_reference(source) for source in sorted(sources, key=_sort_key)]


__all__ = ["CSEStyle"]
