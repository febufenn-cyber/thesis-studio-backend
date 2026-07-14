"""Citation-style registry.

Maps a stable style key to its implementation so renderers and profiles can
select a style by name (``get_citation_style("ieee-2021")``) instead of hardcoding
MLA. MLA remains the default, so existing behavior is unchanged when no style is
specified.
"""

from __future__ import annotations

from app.renderers.styles.apa import APAStyle
from app.renderers.styles.base import CitationStyle, MissingCitationField
from app.renderers.styles.ieee import IEEEStyle
from app.renderers.styles.mla import MLAStyle

DEFAULT_STYLE_KEY = "mla-9"

_STYLES: dict[str, CitationStyle] = {
    MLAStyle.key: MLAStyle(),
    IEEEStyle.key: IEEEStyle(),
    APAStyle.key: APAStyle(),
}


class UnknownCitationStyle(KeyError):
    """The requested citation style key is not registered."""


def get_citation_style(key: str | None = None) -> CitationStyle:
    """Return the style for ``key`` (default MLA). Raises UnknownCitationStyle."""
    resolved = key or DEFAULT_STYLE_KEY
    try:
        return _STYLES[resolved]
    except KeyError as exc:
        raise UnknownCitationStyle(
            f"Unknown citation style {resolved!r}; available: {sorted(_STYLES)}"
        ) from exc


def available_styles() -> list[dict[str, str]]:
    """Metadata for every registered style (for UI/profile pickers)."""
    return [
        {"key": s.key, "edition": s.edition, "mechanism": s.mechanism}
        for s in _STYLES.values()
    ]


__all__ = [
    "CitationStyle",
    "MissingCitationField",
    "UnknownCitationStyle",
    "DEFAULT_STYLE_KEY",
    "get_citation_style",
    "available_styles",
]
