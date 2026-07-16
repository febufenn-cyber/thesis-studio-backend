"""Works Cited entry formatting (FORMAT_SPEC §6, MLA 9).

Entries are produced as lists of canonical Runs so every renderer (docx, md,
txt) shares one formatting source. Missing required fields raise
MissingCitationField — bibliographic data is NEVER guessed (DESIGN.md rule 2).
"""

from __future__ import annotations

from typing import Any, Protocol

from app.canonical.model import Run


class SourceLike(Protocol):
    """Anything with a citation kind and a fields dict (ORM Source or dict)."""

    kind: str
    fields: dict[str, Any]


class MissingCitationField(Exception):
    """A template-required bibliographic field is absent."""

    def __init__(self, field: str, desc: str) -> None:
        self.field = field
        self.desc = desc
        super().__init__(f"Missing citation field {field!r} for {desc}")


# Required fields per kind (FORMAT_SPEC §6 templates).
_REQUIRED: dict[str, tuple[str, ...]] = {
    "book": ("author", "title", "publisher", "year"),
    "translated_book": ("author", "title", "translator", "publisher", "year"),
    "chapter_in_collection": (
        "author", "title", "container", "editor", "publisher", "year", "pages",
    ),
    "journal": ("author", "title", "container", "volume", "number", "year", "pages"),
    "journal_db": (
        "author", "title", "container", "volume", "number", "year", "pages",
        "database", "doi_or_url",
    ),
    "web": ("title", "site", "url"),
    "film": ("title", "director", "studio", "year"),
}


def _req(fields: dict, kind: str, desc: str) -> dict:
    for f in _REQUIRED[kind]:
        if not str(fields.get(f, "")).strip() or "[VERIFY]" in str(fields.get(f, "")):
            raise MissingCitationField(f, desc)
    return fields


def format_entry(kind: str, fields: dict[str, Any]) -> list[Run]:
    """Format one registry source into MLA 9 runs (italic runs for volume titles)."""
    desc = f"{kind}: {fields.get('title') or fields.get('author') or '?'}"
    if kind not in _REQUIRED:
        raise MissingCitationField("kind", f"unknown source kind {kind!r}")
    f = _req(fields, kind, desc)

    author_disp = str(f.get("author", "")).rstrip(".")
    if kind == "book":
        return [
            Run(text=f"{author_disp}. "),
            Run(text=f["title"], italic=True),
            Run(text=f". {f['publisher']}, {f['year']}."),
        ]
    if kind == "translated_book":
        return [
            Run(text=f"{author_disp}. "),
            Run(text=f["title"], italic=True),
            Run(text=f". Translated by {f['translator']}, {f['publisher']}, {f['year']}."),
        ]
    if kind == "chapter_in_collection":
        return [
            Run(text=f"{author_disp}. “{f['title']}.” "),
            Run(text=f["container"], italic=True),
            Run(text=(
                f", edited by {f['editor']}, {f['publisher']}, {f['year']},"
                f" pp. {f['pages']}."
            )),
        ]
    if kind in ("journal", "journal_db"):
        runs = [
            Run(text=f"{author_disp}. “{f['title']}.” "),
            Run(text=f["container"], italic=True),
            Run(text=(
                f", vol. {f['volume']}, no. {f['number']}, {f['year']},"
                f" pp. {f['pages']}."
            )),
        ]
        if kind == "journal_db":
            runs += [
                Run(text=" "),
                Run(text=f["database"], italic=True),
                Run(text=f", {f['doi_or_url']}."),
            ]
        return runs
    if kind == "web":
        runs: list[Run] = []
        if f.get("author"):
            runs.append(Run(text=f"{f['author']}. "))
        runs.append(Run(text=f"“{f['title']}.” "))
        runs.append(Run(text=f["site"], italic=True))
        middle = f", {f['pub_date']}," if f.get("pub_date") else ","
        runs.append(Run(text=f"{middle} {f['url']}."))
        if f.get("access_date"):
            runs.append(Run(text=f" Accessed {f['access_date']}."))
        return runs
    # film
    return [
        Run(text=f["title"], italic=True),
        Run(text=f". Directed by {f['director']}, {f['studio']}, {f['year']}."),
    ]


def fallback_entry(source: SourceLike) -> list[Run]:
    """Review-export rendering for a source whose required fields are missing.

    Never guesses: shows the student's own imported line (raw_entry) — or the
    fields that DO exist — behind a loud marker, so a draft can render while
    the gap stays impossible to miss (never-guess rule, DESIGN.md 2).
    """
    raw = str(getattr(source, "raw_entry", "") or "").strip()
    if not raw:
        f = source.fields or {}
        raw = ", ".join(
            str(v).strip() for k, v in f.items() if str(v).strip() and "[VERIFY]" not in str(v)
        ) or "(no citation details imported)"
    return [
        Run(text="[UNVERIFIED — incomplete citation; shown as imported] "),
        Run(text=raw),
    ]


def _sort_key(source: SourceLike) -> tuple[str, str]:
    author = str(source.fields.get("author", "")).strip()
    title = str(source.fields.get("title", "")).strip()
    surname = author.split(",")[0].strip().lower() if author else title.lower()
    return (surname, title.lower())


def sorted_entries(sources: list[SourceLike]) -> list[list[Run]]:
    """All sources formatted, alphabetised; consecutive same-author → '---.'."""
    ordered = sorted(sources, key=_sort_key)
    entries: list[list[Run]] = []
    prev_author = None
    for s in ordered:
        runs = format_entry(s.kind, s.fields)
        author = str(s.fields.get("author", "")).strip()
        if author and author == prev_author:
            first = runs[0]
            trimmed = first.text[len(author):].lstrip(". ").strip()
            runs = [Run(text=f"---. {trimmed}" if trimmed else "---. ")] + runs[1:]
        prev_author = author or None
        entries.append(runs)
    return entries
