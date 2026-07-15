"""Open-access full-text retrieval (enterprise E4).

For a DOI, find free full text — Europe PMC (full text as text, life-sciences OA)
and Unpaywall (a best-OA link for a "read the source" button). The text feeds
Phase 3 quote verification so quotations are checked against the real source
without anyone uploading a PDF. Fail-closed: no OA text found -> None, never a
fabricated body.
"""

from __future__ import annotations

import re

import httpx

from app.core.config import get_settings

_EPMC_SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
_EPMC_FULLTEXT = "https://www.ebi.ac.uk/europepmc/webservices/rest"
_UNPAYWALL = "https://api.unpaywall.org/v2"

__all__ = ["fetch_fulltext", "oa_link"]

_TAG = re.compile(r"<[^>]+>")


def _strip_xml(xml: str) -> str:
    text = _TAG.sub(" ", xml)
    return re.sub(r"\s+", " ", text).strip()


async def _epmc_lookup(client: httpx.AsyncClient, doi: str) -> tuple[str, str] | None:
    try:
        resp = await client.get(
            _EPMC_SEARCH,
            params={"query": f"DOI:{doi}", "resultType": "core", "format": "json", "pageSize": "1"},
        )
    except httpx.HTTPError:
        return None
    if resp.status_code != 200:
        return None
    try:
        results = ((resp.json() or {}).get("resultList") or {}).get("result") or []
    except ValueError:
        return None
    if not results:
        return None
    r = results[0]
    if str(r.get("isOpenAccess", "")).upper() != "Y":
        return None
    source, ext_id = r.get("source"), r.get("id")
    if not source or not ext_id:
        return None
    return source, ext_id


async def fetch_fulltext(client: httpx.AsyncClient, doi: str) -> dict | None:
    """Return {provider, text} of open-access full text, or None."""
    if not doi or not doi.startswith("10."):
        return None
    found = await _epmc_lookup(client, doi)
    if found is None:
        return None
    source, ext_id = found
    try:
        resp = await client.get(f"{_EPMC_FULLTEXT}/{source}/{ext_id}/fullTextXML")
    except httpx.HTTPError:
        return None
    if resp.status_code != 200 or not resp.text.strip():
        return None
    text = _strip_xml(resp.text)
    if not text:
        return None
    return {"provider": "europepmc", "text": text}


async def oa_link(client: httpx.AsyncClient, doi: str) -> dict | None:
    """Best open-access link for a DOI via Unpaywall (needs a free email)."""
    email = getattr(get_settings(), "UNPAYWALL_EMAIL", "")
    if not email or not doi.startswith("10."):
        return None
    try:
        resp = await client.get(f"{_UNPAYWALL}/{doi}", params={"email": email})
    except httpx.HTTPError:
        return None
    if resp.status_code != 200:
        return None
    try:
        data = resp.json() or {}
    except ValueError:
        return None
    loc = data.get("best_oa_location") or {}
    url = loc.get("url_for_pdf") or loc.get("url")
    if not url:
        return None
    return {"url": url, "is_oa": bool(data.get("is_oa")), "provider": "unpaywall"}
