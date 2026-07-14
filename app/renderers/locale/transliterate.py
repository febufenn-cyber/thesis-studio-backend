"""Fail-closed author-name transliteration (docs/LLD.md 3.7).

Uses PyICU/unidecode when available. When they are not, or the source script is
unsupported, ``certain`` is False and the caller falls back to the source
script — a romanization is never guessed and emitted as if authoritative.
"""

from __future__ import annotations

from typing import NamedTuple


class Transliteration(NamedTuple):
    text: str
    certain: bool


def _ascii_only(text: str) -> bool:
    return all(ord(ch) < 128 for ch in text)


def transliterate_name(name: str, target: str = "Latin") -> Transliteration:
    """Transliterate a name toward ``target`` script; fail closed when unsure."""
    if _ascii_only(name):
        # Already Latin — identity, certain.
        return Transliteration(name, True)

    try:  # pragma: no cover - depends on optional dependency
        from icu import Transliterator  # type: ignore

        result = Transliterator.createInstance(f"Any-{target}").transliterate(name)
        if result and _ascii_only(result):
            return Transliteration(result, True)
    except Exception:
        pass

    try:  # pragma: no cover - depends on optional dependency
        from unidecode import unidecode  # type: ignore

        result = unidecode(name).strip()
        if result and _ascii_only(result):
            return Transliteration(result, True)
    except Exception:
        pass

    # No reliable transliteration available -> keep the source script.
    return Transliteration(name, False)
