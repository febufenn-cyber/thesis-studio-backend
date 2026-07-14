"""Chicago 17th edition, Notes-Bibliography — the notes CitationStyle family.

Notes-Bibliography is the humanities variant of Chicago (history, literature,
the arts). It has two surfaces that differ in punctuation:

- the BIBLIOGRAPHY is an alphabetical reference list built from period-delimited
  entries — ``Author. Title. Publisher, Year.`` — much like author-date but with
  the year moved to the end and no parenthetical date;
- the FOOTNOTES are a numbered stream (see ``notes_engine.build_notes``) whose
  full form uses commas and a parenthetical imprint — ``First Last, Title
  (Publisher, Year), page.`` — and whose short form is ``Last, Short-Title,
  detail.``.

Like the other foundation styles it uses the stored author string verbatim and
reuses the registry's required-field discipline so no bibliographic value is
invented. Chicago's full note normally opens with a place of publication; the
registry stores none, so the imprint is rendered ``(Publisher, Year)``. See
docs/DOMAIN_EXPANSION.md.
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
    """Best-effort surname for the short-form note from a verbatim author string."""
    name = name.strip()
    if not name:
        return name
    if "," in name:  # stored inverted: "Last, First"
        return name.split(",")[0].strip()
    return name.split()[-1]  # "First Last"


class ChicagoNBStyle:
    key = "chicago-nb-17"
    edition = "Chicago 17th (Notes-Bibliography)"
    mechanism = "notes"

    def required_fields(self, source_type: str) -> tuple[str, ...]:
        return _REQUIRED.get(source_type, ())

    # -- Bibliography (alphabetical reference list) --------------------------
    def format_reference(self, source: SourceLike, ordinal: int | None = None) -> list[Run]:
        kind = source.kind
        f = _require(source.fields, kind)

        if kind in ("book", "translated_book"):
            runs = [Run(text=f"{f['author']}. ")]
            runs.append(Run(text=f["title"], italic=True))
            if kind == "translated_book":
                runs.append(
                    Run(text=f". Translated by {f['translator']}. {f['publisher']}, {f['year']}.")
                )
            else:
                runs.append(Run(text=f". {f['publisher']}, {f['year']}."))
            return runs
        if kind == "chapter_in_collection":
            return [
                Run(text=f"{f['author']}. “{f['title']}.” In "),
                Run(text=f["container"], italic=True),
                Run(text=(
                    f", edited by {f['editor']}, {f['pages']}."
                    f" {f['publisher']}, {f['year']}."
                )),
            ]
        if kind in ("journal", "journal_db"):
            runs = [
                Run(text=f"{f['author']}. “{f['title']}.” "),
                Run(text=f["container"], italic=True),
                Run(text=f" {f['volume']}, no. {f['number']} ({f['year']}): {f['pages']}."),
            ]
            if kind == "journal_db":
                runs.append(Run(text=f" {f['doi_or_url']}."))
            return runs
        if kind == "web":
            runs: list[Run] = []
            if f.get("author"):
                runs.append(Run(text=f"{f['author']}. "))
            runs.append(Run(text=f"“{f['title']}.” "))
            runs.append(Run(text=f["site"], italic=True))
            if f.get("pub_date"):
                runs.append(Run(text=f", {f['pub_date']}"))
            runs.append(Run(text=f". {f['url']}."))
            return runs
        # film
        return [
            Run(text=f["title"], italic=True),
            Run(text=f". Directed by {f['director']}. {f['studio']}, {f['year']}."),
        ]

    def sorted_entries(self, sources: list[SourceLike]) -> list[list[Run]]:
        # Notes-Bibliography reference list: alphabetical by author surname.
        return [self.format_reference(source) for source in sorted(sources, key=_sort_key)]

    # -- Footnotes (numbered; see notes_engine.build_notes) ------------------
    def format_note(self, source: SourceLike, first: bool = True) -> list[Run]:
        kind = source.kind
        f = _require(source.fields, kind)

        if not first:
            return self._short_note(kind, f)

        if kind in ("book", "translated_book"):
            runs = [Run(text=f"{f['author']}, ")]
            runs.append(Run(text=f["title"], italic=True))
            if kind == "translated_book":
                runs.append(Run(text=f", trans. {f['translator']}"))
            runs.append(Run(text=f" ({f['publisher']}, {f['year']})."))
            return runs
        if kind == "chapter_in_collection":
            return [
                Run(text=f"{f['author']}, “{f['title']},” in "),
                Run(text=f["container"], italic=True),
                Run(text=(
                    f", ed. {f['editor']} ({f['publisher']}, {f['year']}), {f['pages']}."
                )),
            ]
        if kind in ("journal", "journal_db"):
            runs = [
                Run(text=f"{f['author']}, “{f['title']},” "),
                Run(text=f["container"], italic=True),
                Run(text=f" {f['volume']}, no. {f['number']} ({f['year']}): {f['pages']}."),
            ]
            if kind == "journal_db":
                runs.append(Run(text=f" {f['doi_or_url']}."))
            return runs
        if kind == "web":
            runs = [Run(text=f"{f.get('author', '') + ', ' if f.get('author') else ''}“{f['title']},” ")]
            runs.append(Run(text=f["site"], italic=True))
            runs.append(Run(text=f", {f['url']}."))
            return runs
        # film
        return [
            Run(text=f["title"], italic=True),
            Run(text=f", directed by {f['director']} ({f['studio']}, {f['year']})."),
        ]

    def _short_note(self, kind: str, f: dict) -> list[Run]:
        """Short form: Last, Short-Title, detail. (title italic for books/journals)."""
        author = f.get("author") or f.get("director") or ""
        last = _last_name(author)
        if kind in ("book", "translated_book"):
            return [
                Run(text=f"{last}, "),
                Run(text=f["title"], italic=True),
                Run(text="."),
            ]
        if kind == "chapter_in_collection":
            return [Run(text=f"{last}, “{f['title']},” {f['pages']}.")]
        if kind in ("journal", "journal_db"):
            return [Run(text=f"{last}, “{f['title']},” {f['pages']}.")]
        if kind == "web":
            return [Run(text=f"{last + ', ' if last else ''}“{f['title']}.”")]
        # film
        return [Run(text=f["title"], italic=True), Run(text=".")]


__all__ = ["ChicagoNBStyle"]
