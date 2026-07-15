"""CSL style catalog + fetcher (enterprise E5).

The official Citation Style Language repository carries 10,000+ journal and
publisher styles. Rather than vendoring them all, we resolve a style on demand
from that repository (network-gated by ``CSL_ENABLED``) and cache the XML in
process. A small set of friendly aliases (apa, mla, chicago, ...) maps to the
canonical repo file ids, and citeproc-py's bundled ``harvard1`` is always
available offline so the feature degrades to at least one style with no network.

Fail-closed: an unknown style with no network yields ``None`` (the API then
returns a clear error) — never a silent substitution with a different style.
"""

from __future__ import annotations

import os

import httpx

__all__ = ["resolve_style_xml", "friendly_style_id", "BUNDLED_STYLE_ID", "STYLE_ALIASES"]

# Official repository, master branch. A style id maps to ``<id>.csl``.
_STYLES_BASE = "https://raw.githubusercontent.com/citation-style-language/styles/master"

BUNDLED_STYLE_ID = "harvard1"

# Friendly name -> canonical CSL repository file id.
STYLE_ALIASES = {
    "apa": "apa",
    "mla": "modern-language-association",
    "chicago": "chicago-author-date",
    "chicago-author-date": "chicago-author-date",
    "chicago-note": "chicago-note-bibliography",
    "ieee": "ieee",
    "vancouver": "vancouver",
    "harvard": "harvard-cite-them-right",
    "nature": "nature",
    "ama": "american-medical-association",
    "acs": "american-chemical-society",
    "elsevier": "elsevier-harvard",
}

# Process-lifetime cache of fetched style XML keyed by resolved repo id. Styles
# are static content, so this needs no TTL.
_CACHE: dict[str, str] = {}


def friendly_style_id(style: str) -> str:
    """Map a friendly alias to its canonical repo id (identity if unknown)."""
    key = (style or "").strip().lower()
    return STYLE_ALIASES.get(key, key)


def _bundled_harvard() -> str | None:
    try:
        import citeproc

        path = os.path.join(os.path.dirname(citeproc.__file__), "data", "styles", "harvard1.csl")
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except (ImportError, OSError):
        return None


async def resolve_style_xml(
    client: httpx.AsyncClient | None, style: str, *, enabled: bool = True
) -> str | None:
    """Return the CSL XML for a style id/alias, or ``None`` if unavailable.

    The bundled ``harvard1`` resolves offline. Any other style is fetched from
    the CSL repository only when ``enabled`` and a client is supplied; results
    are cached in process. A 404 / network error yields ``None`` (fail-closed).
    """
    repo_id = friendly_style_id(style)
    if repo_id in (BUNDLED_STYLE_ID, "harvard1"):
        return _bundled_harvard()
    if repo_id in _CACHE:
        return _CACHE[repo_id]
    if not enabled or client is None or not repo_id:
        return None
    # Guard against path traversal / arbitrary URL injection via the style id.
    if "/" in repo_id or ".." in repo_id or not all(c.isalnum() or c in "-_" for c in repo_id):
        return None
    try:
        resp = await client.get(f"{_STYLES_BASE}/{repo_id}.csl")
    except httpx.HTTPError:
        return None
    if resp.status_code != 200 or not resp.text.strip():
        return None
    xml = resp.text
    _CACHE[repo_id] = xml
    return xml
