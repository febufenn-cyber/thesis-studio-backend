"""Research copilot — paper insight from Semantic Scholar (enterprise E3).

For a source with a DOI, returns a one-line TLDR, citation/reference counts, and
a small related-work list (what it cites and what cites it) — the Elicit-style
"what should I read/cite" signal, from the free Semantic Scholar Graph API.
Advisory and fail-closed: no DOI or a transport error yields an empty insight,
never a fabricated summary or reference.
"""

from __future__ import annotations

import httpx

from app.core.config import get_settings

_S2 = "https://api.semanticscholar.org/graph/v1/paper"
_FIELDS = "title,tldr,citationCount,referenceCount,references.title,references.externalIds,citations.title,citations.externalIds"

__all__ = ["paper_insight"]


def _related(items: list, cap: int = 5) -> list[dict]:
    out: list[dict] = []
    for it in (items or [])[:cap]:
        title = (it or {}).get("title")
        if not title:
            continue
        doi = ((it.get("externalIds") or {}) or {}).get("DOI")
        out.append({"title": title, "doi": doi})
    return out


async def paper_insight(client: httpx.AsyncClient, doi: str) -> dict:
    """Return {tldr, citation_count, reference_count, references, citations}."""
    empty = {"found": False, "tldr": None, "citation_count": None,
             "reference_count": None, "references": [], "citations": []}
    if not doi or not doi.startswith("10."):
        return empty
    headers = {}
    key = getattr(get_settings(), "SEMANTIC_SCHOLAR_API_KEY", "")
    if key:
        headers["x-api-key"] = key
    try:
        resp = await client.get(f"{_S2}/DOI:{doi}", params={"fields": _FIELDS}, headers=headers)
    except httpx.HTTPError:
        return empty
    if resp.status_code != 200:
        return empty
    try:
        data = resp.json() or {}
    except ValueError:
        return empty
    tldr = (data.get("tldr") or {}).get("text")
    return {
        "found": True,
        "tldr": tldr,
        "citation_count": data.get("citationCount"),
        "reference_count": data.get("referenceCount"),
        "references": _related(data.get("references")),
        "citations": _related(data.get("citations")),
    }
