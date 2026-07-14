"""Retraction check for a DOI via Crossref update-to notices.

Deliberately conservative: only a positive retraction/withdrawal notice sets
``retracted``. A network failure or missing record returns ``None`` (unknown),
never a false "clean" — the caller treats unknown as "not established", not
"safe".
"""

from __future__ import annotations

import httpx

_BASE = "https://api.crossref.org/works/"


async def check_doi(client: httpx.AsyncClient, doi: str) -> dict | None:
    """Return a retraction dict for a DOI, or ``None`` when not established."""
    try:
        response = await client.get(f"{_BASE}{doi}")
    except httpx.HTTPError:
        return None
    if response.status_code != 200:
        return None
    try:
        work = (response.json() or {}).get("message") or {}
    except ValueError:
        return None

    for update in work.get("update-to") or []:
        kind = str(update.get("type", "")).lower()
        if kind in {"retraction", "withdrawal", "removal"}:
            return {
                "retracted": True,
                "kind": update.get("type"),
                "notice_doi": update.get("DOI"),
                "source": "crossref",
            }
    if work.get("update-policy") and str(work.get("type", "")) == "retraction":
        return {"retracted": True, "kind": "retraction", "source": "crossref"}
    return {"retracted": False, "source": "crossref"}


def status_from_retraction(retraction: dict | None) -> str | None:
    """Map a retraction dict to the Source.retraction_status enum."""
    if not retraction:
        return None
    if retraction.get("retracted"):
        return "retracted"
    return "none"
