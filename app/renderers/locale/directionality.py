"""Script detection and bidi isolation for mixed-direction text."""

from __future__ import annotations

from typing import Literal

from app.canonical.model import Run
from app.renderers.locale.profile import LocaleProfile

# Unicode directional isolates.
_FSI = "⁨"  # First Strong Isolate -- intentional, not obfuscation  # nosec B613
_PDI = "⁩"  # Pop Directional Isolate -- intentional, not obfuscation  # nosec B613

Script = Literal["latin", "arabic", "hebrew", "han", "kana", "other", "mixed"]


def _char_script(ch: str) -> str:
    code = ord(ch)
    if 0x0600 <= code <= 0x06FF or 0x0750 <= code <= 0x077F or 0x08A0 <= code <= 0x08FF:
        return "arabic"
    if 0x0590 <= code <= 0x05FF:
        return "hebrew"
    if 0x4E00 <= code <= 0x9FFF or 0x3400 <= code <= 0x4DBF:
        return "han"
    if 0x3040 <= code <= 0x30FF:
        return "kana"
    if (0x41 <= code <= 0x5A) or (0x61 <= code <= 0x7A) or (0xC0 <= code <= 0x24F):
        return "latin"
    return "other"


def script_of(text: str) -> Script:
    """Dominant script of a string (``mixed`` when strong scripts disagree)."""
    seen: set[str] = set()
    for ch in text:
        s = _char_script(ch)
        if s in {"latin", "arabic", "hebrew", "han", "kana"}:
            seen.add(s)
    if not seen:
        return "other"
    if len(seen) == 1:
        return next(iter(seen))  # type: ignore[return-value]
    return "mixed"


_RTL_SCRIPTS = {"arabic", "hebrew"}


def emit_directional_runs(runs: list[Run], profile: LocaleProfile) -> list[Run]:
    """Wrap runs whose script opposes the document direction in FSI/PDI isolates.

    For an RTL document, a Latin run (a DOI/URL/number) is isolated so it renders
    in correct visual order. LTR documents and runs matching the base direction
    are returned unchanged.
    """
    if profile.direction != "rtl":
        return list(runs)
    out: list[Run] = []
    for run in runs:
        script = script_of(run.text)
        if script in {"latin"} or (script == "mixed" and any(_char_script(c) == "latin" for c in run.text)):
            out.append(Run(text=f"{_FSI}{run.text}{_PDI}", italic=run.italic))
        else:
            out.append(run)
    return out
