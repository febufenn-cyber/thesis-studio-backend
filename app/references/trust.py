"""Source & Journal Trust intelligence (enterprise E1).

Assembles free, public indexing signals into an advisory "is this source safe to
cite?" verdict: journal reputation/indexing (OpenAlex, incl. its DOAJ flag),
retraction status (Crossref), and — when a free key is configured — self-archiving
rights (Sherpa Romeo). Advisory only and fair-by-design: absence of a signal is
reported as *unknown*, never as "predatory" or "trusted". Never sets a
human-owned verified bit.
"""

from __future__ import annotations

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.source import Source
from app.references.http import build_client
from app.references.retraction import check_doi

_OPENALEX_SOURCES = "https://api.openalex.org/sources"
_SHERPA = "https://v2.sherpa.ac.uk/cgi/retrieve"

__all__ = ["assess_source_trust"]


async def _journal_signals(client: httpx.AsyncClient, title: str) -> dict | None:
    """Reputation/indexing signals for a journal title from OpenAlex (free)."""
    try:
        resp = await client.get(_OPENALEX_SOURCES, params={"search": title, "per-page": "1"})
    except httpx.HTTPError:
        return None
    if resp.status_code != 200:
        return None
    try:
        results = (resp.json() or {}).get("results") or []
    except ValueError:
        return None
    if not results:
        return None
    s = results[0]
    stats = s.get("summary_stats") or {}
    return {
        "matched_name": s.get("display_name"),
        "in_doaj": bool(s.get("is_in_doaj")),
        "open_access": bool(s.get("is_oa")),
        "publisher": s.get("host_organization_name"),
        "works_count": s.get("works_count"),
        "cited_by_count": s.get("cited_by_count"),
        "h_index": stats.get("h_index"),
    }


async def _self_archiving(client: httpx.AsyncClient, title: str, api_key: str) -> dict | None:
    """Self-archiving policy from Sherpa Romeo (free key). Optional."""
    params = {
        "item-type": "publication", "format": "Json", "api-key": api_key,
        "filter": f'[["title","equals","{title}"]]',
    }
    try:
        resp = await client.get(_SHERPA, params=params)
    except httpx.HTTPError:
        return None
    if resp.status_code != 200:
        return None
    try:
        items = (resp.json() or {}).get("items") or []
    except ValueError:
        return None
    if not items:
        return None
    policies = items[0].get("publisher_policy") or []
    can_archive = any(
        perm.get("article_version") for policy in policies for perm in (policy.get("permitted_oa") or [])
    )
    return {"policy_found": True, "can_self_archive": bool(can_archive)}


def _verdict(retraction: dict | None, journal: dict | None) -> tuple[str, list[str]]:
    """Fair, fail-closed verdict from the assembled signals."""
    signals: list[str] = []
    if retraction and retraction.get("retracted"):
        signals.append("This work is flagged as retracted or withdrawn.")
        return "caution", signals

    if journal is None:
        signals.append("No indexing record found for the journal — verify the venue independently.")
        return "unknown", signals

    if journal.get("in_doaj"):
        signals.append("Listed in the Directory of Open Access Journals (vetted OA).")
    if (journal.get("h_index") or 0) > 0 or (journal.get("cited_by_count") or 0) > 0:
        signals.append(
            f"Established citation record (h-index {journal.get('h_index')}, "
            f"{journal.get('cited_by_count')} citations)."
        )
    if journal.get("in_doaj") or (journal.get("h_index") or 0) > 0:
        return "reputable", signals

    signals.append("Indexed, but with limited reputation signals — verify the venue.")
    return "listed", signals


async def assess_source_trust(
    db: AsyncSession, source: Source, *, client: httpx.AsyncClient | None = None
) -> dict:
    """Assemble an advisory trust report for a registry source."""
    settings = get_settings()
    enabled = client is not None or getattr(settings, "SOURCE_TRUST_ENABLED", True)
    fields = source.fields or {}
    title = str(fields.get("container") or fields.get("site") or "").strip()
    doi = str(fields.get("doi_or_url") or (source.identifiers or {}).get("doi") or "").strip()

    if not enabled:
        return {"advisory": True, "verdict": "unknown", "journal": None, "retraction": None, "signals": [], "self_archiving": None}

    owns = client is None
    active = client or build_client()
    try:
        retraction = None
        if doi and doi.startswith("10."):
            retraction = await check_doi(active, doi)
        journal = await _journal_signals(active, title) if title else None
        self_arch = None
        key = getattr(settings, "SHERPA_ROMEO_API_KEY", "")
        if key and title:
            self_arch = await _self_archiving(active, title, key)
    finally:
        if owns:
            await active.aclose()

    verdict, signals = _verdict(retraction, journal)
    return {
        "advisory": True,
        "verdict": verdict,  # reputable | listed | unknown | caution
        "journal": journal,
        "retraction": retraction,
        "self_archiving": self_arch,
        "signals": signals,
    }
