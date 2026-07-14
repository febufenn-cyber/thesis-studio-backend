"""Research-consent + transparency API (docs/LLD.md 3.8).

Opt-in, deny-by-default. Consent is pinned to the current terms version. The
transparency endpoint shows exactly what would be shared about a project
(anonymized, read-only). Owner-guarded.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, fetch_owned_project
from app.db.deps import get_db
from app.research.consent import (
    SCOPES,
    current_terms_version,
    grant_research_consent,
    list_consents,
    revoke_research_consent,
)
from app.research.corpus import shared_preview

router = APIRouter(tags=["research"])

_Scope = Literal["revision_history", "citation_patterns", "ai_provenance", "all"]


class ConsentRequest(BaseModel):
    scope: _Scope
    terms_version: str


@router.post("/research/consent", status_code=status.HTTP_201_CREATED)
async def grant_consent(
    body: ConsentRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Record a research-donation consent for the current terms version."""
    current = current_terms_version()
    if not current:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Research donation is not currently available.",
        )
    if body.terms_version != current:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Consent must be for the current terms version ({current}).",
        )
    consent = await grant_research_consent(
        db,
        user_id=current_user.id,
        scope=body.scope,
        terms_version=body.terms_version,
        evidence={},
    )
    await db.commit()
    return {
        "id": str(consent.id),
        "scope": consent.scope,
        "terms_version": consent.terms_version,
        "revoked_at": None,
    }


@router.delete("/research/consent/{scope}")
async def revoke_consent(
    scope: str,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Revoke consent for a scope (idempotent)."""
    if scope not in SCOPES:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown scope.")
    revoked = await revoke_research_consent(db, user_id=current_user.id, scope=scope)
    await db.commit()
    return {"scope": scope, "revoked": revoked}


@router.get("/research/consent")
async def get_consents(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List the caller's consent grants."""
    rows = await list_consents(db, current_user.id)
    return {
        "terms_version": current_terms_version(),
        "consents": [
            {
                "scope": c.scope,
                "terms_version": c.terms_version,
                "granted_at": c.granted_at.isoformat() if c.granted_at else None,
                "revoked_at": c.revoked_at.isoformat() if c.revoked_at else None,
            }
            for c in rows
        ],
    }


@router.get("/projects/{project_id}/research/shared")
async def research_shared(
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Show the de-identified projection that would be exported for this project."""
    project = await fetch_owned_project(db, project_id, current_user.id)
    return {"shared": await shared_preview(db, project)}
