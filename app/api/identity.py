"""Verified identity API (enterprise E2).

Canonical affiliation (ROR) and author (ORCID) lookups from free registries, for
verified-identity chips. Read-only, authenticated; fail-closed on missing data.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.config import get_settings
from app.db.deps import get_db
from app.integrations.orcid import OrcidClient, is_well_formed
from app.integrations.ror import search_organizations
from app.references.http import build_client

router = APIRouter(tags=["identity"])


def _enabled() -> bool:
    return bool(getattr(get_settings(), "IDENTITY_LOOKUP_ENABLED", True))


@router.get("/identity/organizations")
async def lookup_organizations(
    q: str,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Resolve an affiliation string to canonical ROR institution records."""
    if not _enabled():
        return {"query": q, "matches": []}
    client = build_client()
    try:
        matches = await search_organizations(client, q)
    finally:
        await client.aclose()
    return {"query": q, "matches": matches}


@router.get("/identity/orcid/{orcid}")
async def resolve_orcid(
    orcid: str,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Resolve a public ORCID record to a verified author name."""
    if not is_well_formed(orcid):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Malformed ORCID iD.")
    if not _enabled():
        return {"orcid": orcid, "name": None, "verified": False}
    client = build_client()
    try:
        record = await OrcidClient(client).resolve(orcid)
    finally:
        await client.aclose()
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ORCID could not be resolved.")
    return {**record, "verified": True}
