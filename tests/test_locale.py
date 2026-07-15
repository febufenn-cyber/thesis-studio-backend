"""Locale registry, directionality, transliteration (docs/LLD.md 3.7)."""

from __future__ import annotations

from app.canonical.model import Run
from app.renderers.locale import (
    emit_directional_runs,
    resolve_locale,
    script_of,
    transliterate_name,
)
from app.renderers.locale.profile import list_locales


def test_english_resolves_to_none() -> None:
    assert resolve_locale("") is None
    assert resolve_locale(None) is None


def test_regional_and_base_fallback() -> None:
    assert resolve_locale("ar").direction == "rtl"
    assert resolve_locale("de").tag == "de-DE"  # base -> regional
    assert resolve_locale("xx-YY") is None


def test_list_locales_includes_direction() -> None:
    tags = {loc["tag"]: loc for loc in list_locales()}
    assert tags["ar"]["direction"] == "rtl"
    assert tags["zh-Hans"]["direction"] == "ltr"


def test_script_detection() -> None:
    assert script_of("Hello") == "latin"
    assert script_of("مرحبا") == "arabic"
    assert script_of("你好") == "han"
    assert script_of("Hello مرحبا") == "mixed"


def test_ltr_locale_leaves_runs_unchanged() -> None:
    de = resolve_locale("de-DE")
    runs = [Run(text="Hallo"), Run(text="Welt", italic=True)]
    assert emit_directional_runs(runs, de) == runs


def test_rtl_isolates_latin_runs() -> None:
    ar = resolve_locale("ar")
    runs = [Run(text="مرحبا"), Run(text="doi:10.1/x")]
    out = emit_directional_runs(runs, ar)
    assert out[0].text == "مرحبا"  # RTL run unchanged
    assert out[1].text.startswith("⁨") and out[1].text.endswith("⁩")


def test_transliteration_is_identity_for_ascii() -> None:
    result = transliterate_name("Woolf, Virginia")
    assert result.certain is True
    assert result.text == "Woolf, Virginia"


def test_transliteration_fails_closed_without_lib() -> None:
    # No ICU/unidecode installed -> non-Latin cannot be romanized; keep source.
    result = transliterate_name("陈")
    assert result.certain is False
    assert result.text == "陈"
