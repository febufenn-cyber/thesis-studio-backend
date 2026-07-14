"""Deposit + ORCID API (docs/LLD_MISSING_FEATURES.md MF3).

Partner-gated and fail-closed: an unset ZENODO_TOKEN returns 503 with no network
call. Owner-guarded. ORCID is verified via the public API before being stored.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, fetch_owned_project
from app.core.config import get_settings
from app.db.deps import get_db
from app.integrations.deposit import ZenodoTarget
from app.integrations.orcid import OrcidClient, is_well_formed
from app.models.deposit import Deposit
from app.models.export import Export
from app.references.http import build_client
from app.services.deposit_service import create_deposit

router = APIRouter(tags=["projects"])


class DepositRequest(BaseModel):
    export_id: UUID
    target: str = "zenodo"


class OrcidRequest(BaseModel):
    orcid: str


def _deposit_dict(d: Deposit) -> dict:
    return {
        "id": str(d.id),
        "target": d.target,
        "status": d.status,
        "doi": d.doi,
        "landing_url": d.landing_url,
        "error_message": d.error_message,
        "sandbox": d.sandbox,
    }


@router.post("/projects/{project_id}/deposits", status_code=status.HTTP_201_CREATED)
async def create_project_deposit(
    project_id: UUID,
    body: DepositRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Deposit a ready export to an external repository and mint a DOI."""
    project = await fetch_owned_project(db, project_id, current_user.id)
    settings = get_settings()
    if body.target != "zenodo":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported deposit target.")
    if not settings.ZENODO_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Deposit is not configured (missing repository credentials).",
        )
    export = (
        await db.execute(
            select(Export).where(Export.id == body.export_id, Export.project_id == project.id)
        )
    ).scalar_one_or_none()
    if export is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Export not found.")
    if export.status != "ready" or not export.storage_key:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Export is not ready for deposit.")

    sandbox = "sandbox" in settings.ZENODO_BASE_URL
    client = build_client()
    try:
        target = ZenodoTarget(client, settings.ZENODO_TOKEN, settings.ZENODO_BASE_URL)
        user = current_user
        deposit = await create_deposit(
            db, project, export, current_user.id, target,
            orcid=getattr(user, "orcid", None), sandbox=sandbox,
        )
    finally:
        await client.aclose()
    await db.commit()
    return _deposit_dict(deposit)


@router.get("/projects/{project_id}/deposits")
async def list_project_deposits(
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    project = await fetch_owned_project(db, project_id, current_user.id)
    rows = list(
        (
            await db.execute(
                select(Deposit).where(Deposit.project_id == project.id).order_by(Deposit.created_at.desc())
            )
        ).scalars()
    )
    return {"deposits": [_deposit_dict(d) for d in rows]}


@router.post("/orcid")
async def link_orcid(
    body: OrcidRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Verify an ORCID via the public API and store it on the user."""
    if not is_well_formed(body.orcid):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Malformed ORCID iD.")
    client = build_client()
    try:
        verified = await OrcidClient(client).verify(body.orcid)
    finally:
        await client.aclose()
    if not verified:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="ORCID could not be verified.")
    current_user.orcid = body.orcid
    current_user.orcid_verified_at = datetime.now(timezone.utc)
    await db.commit()
    return {"orcid": body.orcid, "verified": True}


@router.delete("/orcid")
async def unlink_orcid(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    current_user.orcid = None
    current_user.orcid_verified_at = None
    await db.commit()
    return {"orcid": None}
