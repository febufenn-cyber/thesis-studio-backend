"""
inline_markdown.py — minimal markdown parser for inline italics in body prose.

The thesis-content model emits paragraphs with markdown-style italic markers:

    "Boal's *Theatre of the Oppressed* draws on Freire's *Pedagogy of the Oppressed*."

We parse this into a sequence of (text, italic) tuples so the formatter can
emit multiple python-docx runs within a single paragraph, with the right
portions italicized.

Italics only — bold and other markdown features are deliberately NOT supported.
A thesis body uses italics for work titles per MLA, and bold only at the
heading level (which the formatter handles separately).

Escaping: a literal asterisk can be written as `\\*` and a literal underscore
as `\\_`. These survive parsing as plain characters.
"""

from __future__ import annotations
import re


# Match *italic* or _italic_, but NOT inside word boundaries for underscores
# (so `snake_case_var` isn't broken). Asterisks can appear adjacent to letters
# because nobody writes asterisks in thesis prose unless they mean italic.
_ITALIC_RE = re.compile(
    r'(?<!\\)\*([^*\n]+?)\*'      # *italic*
    r'|'
    r'(?<!\\)(?<![A-Za-z0-9])_([^_\n]+?)_(?![A-Za-z0-9])',  # _italic_ at word boundary
)

_ESCAPE_RE = re.compile(r'\\([*_])')


def parse_inline_runs(text: str) -> list[tuple[str, bool]]:
    """
    Parse text with markdown italic markers into (text, italic) tuples.

    >>> parse_inline_runs("Boal's *Theatre of the Oppressed* (1979)")
    [("Boal's ", False), ('Theatre of the Oppressed', True), (' (1979)', False)]

    >>> parse_inline_runs("plain text")
    [('plain text', False)]

    >>> parse_inline_runs(r"escaped \\*asterisk\\*")
    [('escaped *asterisk*', False)]
    """
    if not text:
        return []

    parts: list[tuple[str, bool]] = []
    cursor = 0

    for m in _ITALIC_RE.finditer(text):
        if m.start() > cursor:
            plain = text[cursor:m.start()]
            parts.append((_unescape(plain), False))
        italic_text = m.group(1) if m.group(1) is not None else m.group(2)
        parts.append((_unescape(italic_text), True))
        cursor = m.end()

    if cursor < len(text):
        parts.append((_unescape(text[cursor:]), False))

    # Coalesce adjacent runs with the same italic flag (cleaner output)
    coalesced: list[tuple[str, bool]] = []
    for run_text, italic in parts:
        if coalesced and coalesced[-1][1] == italic:
            coalesced[-1] = (coalesced[-1][0] + run_text, italic)
        else:
            coalesced.append((run_text, italic))
    return coalesced


def _unescape(text: str) -> str:
    """Convert `\\*` to `*` and `\\_` to `_`."""
    return _ESCAPE_RE.sub(r'\1', text)


if __name__ == '__main__':
    # Smoke tests
    cases = [
        ("Boal's *Theatre of the Oppressed* (1979)",
         [("Boal's ", False), ('Theatre of the Oppressed', True), (' (1979)', False)]),
        ("plain text", [('plain text', False)]),
        (r"escaped \*asterisk\*", [('escaped *asterisk*', False)]),
        ("*opening italic* then plain",
         [('opening italic', True), (' then plain', False)]),
        ("plain then *closing italic*",
         [('plain then ', False), ('closing italic', True)]),
        ("Freire's *Pedagogy of the Oppressed* and Boal's *Theatre of the Oppressed*",
         [("Freire's ", False), ('Pedagogy of the Oppressed', True),
          (" and Boal's ", False), ('Theatre of the Oppressed', True)]),
        ("snake_case_variable should not italicize",
         [('snake_case_variable should not italicize', False)]),
    ]
    for input_text, expected in cases:
        actual = parse_inline_runs(input_text)
        status = "OK" if actual == expected else "FAIL"
        print(f"[{status}] {input_text!r}")
        if status == "FAIL":
            print(f"    expected: {expected}")
            print(f"    actual:   {actual}")
