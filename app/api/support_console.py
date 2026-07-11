"""Permissioned support console endpoints without default manuscript access."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.collaboration.capabilities import require_project_capability
from app.commercial.support import SupportError, diagnostic_bundle, retry_job
from app.db.deps import get_db
from app.models.job import Job


router = APIRouter(tags=["support-console"])


class SupportJustification(BaseModel):
    justification: str = Field(..., min_length=10, max_length=4000)


@router.post("/support/projects/{project_id}/diagnostic-bundle")
async def generate_diagnostic(
    project_id: UUID,
    body: SupportJustification,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    access = await require_project_capability(
        db, project_id, current_user, "support.diagnostic"
    )
    bundle = await diagnostic_bundle(
        db,
        access.project,
        support_user_id=current_user.id,
        justification=body.justification,
    )
    await db.commit()
    return bundle


@router.post("/support/projects/{project_id}/jobs/{job_id}/retry")
async def retry_failed_job(
    project_id: UUID,
    job_id: UUID,
    body: SupportJustification,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_project_capability(db, project_id, current_user, "support.retry_job")
    row = (
        await db.execute(
            select(Job).where(Job.id == job_id, Job.project_id == project_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")
    try:
        await retry_job(
            db,
            row,
            support_user_id=current_user.id,
            justification=body.justification,
        )
    except SupportError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await db.commit()
    return {
        "id": row.id,
        "kind": row.kind,
        "queue": row.queue_name,
        "status": row.status,
        "available_at": row.available_at,
        "content_accessed": False,
    }
