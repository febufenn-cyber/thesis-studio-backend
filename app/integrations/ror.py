"""Research Organization Registry (ROR) client (enterprise E2).

Free, keyless. Resolves an affiliation string to canonical institution records
(ROR id, official name, country) so the UI can show a verified-affiliation chip.
Fail-closed: any transport error yields no matches, never a guessed institution.
"""

from __future__ import annotations

import httpx

_API = "https://api.ror.org/organizations"

__all__ = ["search_organizations"]


async def search_organizations(client: httpx.AsyncClient, query: str, *, limit: int = 5) -> list[dict]:
    """Return canonical ROR matches for an affiliation string (best-effort)."""
    if not query.strip():
        return []
    try:
        response = await client.get(_API, params={"query": query})
    except httpx.HTTPError:
        return []
    if response.status_code != 200:
        return []
    try:
        items = (response.json() or {}).get("items") or []
    except ValueError:
        return []
    out: list[dict] = []
    for org in items[:limit]:
        country = (org.get("country") or {}).get("country_name")
        out.append(
            {
                "ror_id": org.get("id"),
                "name": org.get("name"),
                "country": country,
                "established": org.get("established"),
            }
        )
    return out
