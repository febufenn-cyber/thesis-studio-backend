"""Footnote assembly for notes-mechanism citation styles (Chicago NB, etc.).

Notes styles carry two outputs: an alphabetical bibliography (handled by the
style's ``sorted_entries``) and a numbered stream of footnotes. This helper owns
only the footnote stream: it walks the *ordered* list of cited sources and picks,
per citation, the right note form —

- first appearance of a source        -> style.format_note(source, first=True)
- immediate repeat of that same source -> "Ibid."
- later (non-adjacent) repeat          -> style.format_note(source, first=False)

Sources are compared by identity (``is``)/position, never by value, so two
distinct sources that happen to share a field never collapse into an "Ibid.".
The function is pure and DB-free; it only builds canonical ``Run`` lists.
"""

from __future__ import annotations

from app.canonical.model import Run


def build_notes(sources: list, style) -> list[list[Run]]:
    """Return numbered footnote entries (1..n) for ``sources`` in citation order.

    ``style`` must expose ``format_note(source, first=bool) -> list[Run]``.
    """
    entries: list[list[Run]] = []
    prev = None
    for index, source in enumerate(sources):
        if prev is not None and source is prev:
            body = [Run(text="Ibid.")]
        elif any(source is earlier for earlier in sources[:index]):
            body = style.format_note(source, first=False)
        else:
            body = style.format_note(source, first=True)
        entries.append([Run(text=f"{index + 1}. ")] + list(body))
        prev = source
    return entries


__all__ = ["build_notes"]
