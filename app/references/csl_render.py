"""CSL citeproc rendering (enterprise E5).

Formats registry sources — already serialized to CSL-JSON by
``app.renderers.csl.to_csl_json`` — into a real bibliography in any Citation
Style Language style, using the citeproc-py engine and its bundled locales.

This is a *formatter*, not a fact source: it renders only the fields the
registry already holds and never invents authors, dates or titles. If a style
cannot be parsed the caller fails closed (no bibliography) rather than emitting a
guessed one. Rendering is pure/CPU-bound and safe to run inline.
"""

from __future__ import annotations

import io

__all__ = ["render_bibliography", "CSLRenderError"]


class CSLRenderError(RuntimeError):
    """Raised when a CSL style is unparseable or rendering fails."""


def render_bibliography(
    csl_items: list[dict], style_xml: str | bytes, *, output: str = "html"
) -> list[str]:
    """Render CSL-JSON items into formatted bibliography entries.

    ``style_xml`` is the raw CSL style document. ``output`` is 'html' or 'text'.
    Returns one formatted string per item, in input order. Items with no CSL id
    are skipped. Raises :class:`CSLRenderError` on an unparseable style.
    """
    # Imported lazily so the dependency is only required when the feature runs.
    from citeproc import (
        Citation,
        CitationItem,
        CitationStylesBibliography,
        CitationStylesStyle,
        formatter,
    )
    from citeproc.source.json import CiteProcJSON

    items = [it for it in (csl_items or []) if it.get("id")]
    if not items:
        return []

    raw = style_xml.encode("utf-8") if isinstance(style_xml, str) else style_xml
    try:
        style = CitationStylesStyle(io.BytesIO(raw), validate=False)
    except Exception as exc:  # noqa: BLE001 - any parse failure fails closed
        raise CSLRenderError(f"Unparseable CSL style: {exc}") from exc

    fmt = formatter.plain if output == "text" else formatter.html
    source = CiteProcJSON(items)
    bib = CitationStylesBibliography(style, source, fmt)
    for item in items:
        bib.register(Citation([CitationItem(item["id"])]))

    try:
        rendered = bib.bibliography()
    except Exception as exc:  # noqa: BLE001 - style/engine incompatibility -> fail closed
        raise CSLRenderError(f"Bibliography rendering failed: {exc}") from exc
    return [str(entry) for entry in rendered]
