"""Integrity Report API (docs/LLD_MISSING_FEATURES.md MF4).

Read-only. Access mirrors Phase 6: the project owner, or a committee member
holding VIEW_CONTENT. 404 (not 403) on a foreign project to avoid enumeration.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.collaboration.committee import SupervisionPermission, member_has_permission
from app.db.deps import get_db
from app.models.project import Project
from app.services.integrity_report import build_integrity_report

router = APIRouter(tags=["projects"])


async def _readable_project(db: AsyncSession, project_id: UUID, user) -> Project:
    project = (
        await db.execute(select(Project).where(Project.id == project_id))
    ).scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
    if project.user_id == user.id:
        return project
    if await member_has_permission(db, project_id, user.id, SupervisionPermission.VIEW_CONTENT):
        return project
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")


@router.get("/projects/{project_id}/integrity-report")
async def integrity_report(
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Aggregate provenance + verification + reference + marker signals."""
    project = await _readable_project(db, project_id, current_user)
    return await build_integrity_report(db, project)
