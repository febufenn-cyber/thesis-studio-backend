"""Limited collaboration presence without live cursors or concurrent text merging."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.collaboration.capabilities import require_project_capability, resolve_project_access
from app.db.deps import get_db
from app.models.presence import ProjectPresence
from app.models.user import User


router = APIRouter(tags=["collaboration"])


class PresenceHeartbeat(BaseModel):
    activity: Literal["viewing", "editing", "reviewing", "formatting"] = "viewing"
    scope: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}


_ALLOWED_SCOPE_KEYS = {"type", "chapter_id", "block_id", "review_cycle_id", "mode"}


def _safe_scope(scope: dict[str, Any]) -> dict[str, Any]:
    """Keep presence operational; never persist prose, selection text or prompts."""

    result: dict[str, Any] = {}
    for key in _ALLOWED_SCOPE_KEYS:
        value = scope.get(key)
        if value is None:
            continue
        text = str(value)
        if len(text) <= 120:
            result[key] = text
    return result


@router.put("/projects/{project_id}/presence")
async def heartbeat_presence(
    project_id: UUID,
    body: PresenceHeartbeat,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    access = await require_project_capability(
        db, project_id, current_user, "project.read_metadata"
    )
    activity = body.activity
    if activity == "editing" and not (
        "project.edit_content" in access.capabilities
        or "project.edit_structure" in access.capabilities
        or "project.edit_metadata" in access.capabilities
    ):
        activity = "viewing"
    if activity == "reviewing" and not (
        "project.comment" in access.capabilities
        or "project.approve_chapter" in access.capabilities
    ):
        activity = "viewing"
    if activity == "formatting" and "project.edit_structure" not in access.capabilities:
        activity = "viewing"

    now = datetime.now(timezone.utc)
    row = (
        await db.execute(
            select(ProjectPresence).where(
                ProjectPresence.project_id == project_id,
                ProjectPresence.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = ProjectPresence(project_id=project_id, user_id=current_user.id)
        db.add(row)
    row.activity = activity
    row.scope = _safe_scope(body.scope)
    row.last_seen_at = now
    row.expires_at = now + timedelta(seconds=90)
    await db.commit()
    await db.refresh(row)
    return {
        "project_id": project_id,
        "activity": row.activity,
        "scope": row.scope,
        "expires_at": row.expires_at,
        "live_cursors": False,
        "concurrent_text_merge": False,
    }


@router.get("/projects/{project_id}/presence")
async def list_presence(
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    await require_project_capability(db, project_id, current_user, "project.read_metadata")
    now = datetime.now(timezone.utc)
    await db.execute(
        delete(ProjectPresence).where(
            ProjectPresence.project_id == project_id,
            ProjectPresence.expires_at <= now,
        )
    )
    rows = list(
        (
            await db.execute(
                select(ProjectPresence, User)
                .join(User, User.id == ProjectPresence.user_id)
                .where(
                    ProjectPresence.project_id == project_id,
                    ProjectPresence.expires_at > now,
                )
                .order_by(ProjectPresence.last_seen_at.desc())
            )
        ).all()
    )
    result: list[dict] = []
    for presence, user in rows:
        access = await resolve_project_access(db, project_id, user)
        if access is None:
            continue
        result.append(
            {
                "user_id": user.id,
                "display_name": user.full_name or user.email,
                "role": access.role,
                "activity": presence.activity,
                "scope": presence.scope,
                "last_seen_at": presence.last_seen_at,
                "expires_at": presence.expires_at,
            }
        )
    await db.commit()
    return result


@router.delete("/projects/{project_id}/presence")
async def leave_presence(
    project_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_project_capability(db, project_id, current_user, "project.read_metadata")
    await db.execute(
        delete(ProjectPresence).where(
            ProjectPresence.project_id == project_id,
            ProjectPresence.user_id == current_user.id,
        )
    )
    await db.commit()
    return {"project_id": project_id, "present": False}
