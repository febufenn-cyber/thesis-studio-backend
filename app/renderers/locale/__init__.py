"""Locale-aware rendering support (docs/LLD.md 3.7).

A locale registry (direction, name order, punctuation) plus fail-closed
transliteration and directionality helpers. English ("" locale) short-circuits
to today's exact behavior, so existing documents render unchanged.
"""

from __future__ import annotations

from app.renderers.locale.directionality import emit_directional_runs, script_of
from app.renderers.locale.profile import (
    LocaleProfile,
    list_locales,
    resolve_locale,
)
from app.renderers.locale.transliterate import Transliteration, transliterate_name

__all__ = [
    "LocaleProfile",
    "resolve_locale",
    "list_locales",
    "script_of",
    "emit_directional_runs",
    "transliterate_name",
    "Transliteration",
]
