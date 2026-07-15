"""Locale registry — direction, name order, and punctuation per locale."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Direction = Literal["ltr", "rtl"]


@dataclass(frozen=True)
class LocaleProfile:
    tag: str
    label: str
    direction: Direction
    name_order: Literal["given_family", "family_given"]
    quote_open: str
    quote_close: str
    list_sep: str


_LOCALES: dict[str, LocaleProfile] = {
    "en": LocaleProfile("en", "English", "ltr", "family_given", "“", "”", ", "),
    "de-DE": LocaleProfile("de-DE", "German", "ltr", "family_given", "„", "“", ", "),
    "fr-FR": LocaleProfile("fr-FR", "French", "ltr", "family_given", "« ", " »", ", "),
    "zh-Hans": LocaleProfile("zh-Hans", "Chinese (Simplified)", "ltr", "family_given", "“", "”", "、"),
    "ja": LocaleProfile("ja", "Japanese", "ltr", "family_given", "「", "」", "、"),
    "ar": LocaleProfile("ar", "Arabic", "rtl", "family_given", "«", "»", "، "),
    "fa-IR": LocaleProfile("fa-IR", "Persian", "rtl", "family_given", "«", "»", "، "),
    "he": LocaleProfile("he", "Hebrew", "rtl", "family_given", "”", "”", ", "),
}


def resolve_locale(tag: str | None) -> LocaleProfile | None:
    """Return the LocaleProfile for a tag, or ``None`` for English/empty.

    Falls back from a regional tag (``de-DE``) to its base language (``de``) when
    only the base is registered, and vice versa.
    """
    if not tag:
        return None
    if tag in _LOCALES:
        return _LOCALES[tag]
    base = tag.split("-")[0]
    if base in _LOCALES:
        return _LOCALES[base]
    for key, profile in _LOCALES.items():
        if key.split("-")[0] == base:
            return profile
    return None


def is_registered(tag: str) -> bool:
    return resolve_locale(tag) is not None


def list_locales() -> list[dict]:
    return [
        {"tag": p.tag, "label": p.label, "direction": p.direction}
        for p in _LOCALES.values()
    ]
