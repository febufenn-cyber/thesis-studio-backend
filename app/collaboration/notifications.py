"""Event-driven in-app notifications that avoid leaking thesis prose."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenancy import Notification, NotificationPreference, ProjectMembership


async def notify(
    db: AsyncSession,
    user_id: UUID,
    *,
    kind: str,
    title: str,
    body: str,
    project_id: UUID | None = None,
    data: dict | None = None,
) -> Notification | None:
    preference = (
        await db.execute(
            select(NotificationPreference).where(
                NotificationPreference.user_id == user_id,
                NotificationPreference.kind == kind,
            )
        )
    ).scalar_one_or_none()
    if preference and preference.cadence == "muted":
        return None
    row = Notification(
        user_id=user_id,
        project_id=project_id,
        kind=kind,
        title=title[:300],
        body=body[:2000],
        data=data or {},
        privacy_level="metadata_only",
    )
    db.add(row)
    await db.flush()
    return row


async def notify_project_roles(
    db: AsyncSession,
    project_id: UUID,
    roles: set[str],
    *,
    kind: str,
    title: str,
    body: str,
    exclude_user_id: UUID | None = None,
    data: dict | None = None,
) -> list[Notification]:
    memberships = list(
        (
            await db.execute(
                select(ProjectMembership).where(
                    ProjectMembership.project_id == project_id,
                    ProjectMembership.status == "active",
                    ProjectMembership.role.in_(roles),
                )
            )
        ).scalars()
    )
    rows: list[Notification] = []
    for membership in memberships:
        if membership.user_id == exclude_user_id:
            continue
        row = await notify(
            db,
            membership.user_id,
            kind=kind,
            title=title,
            body=body,
            project_id=project_id,
            data=data,
        )
        if row:
            rows.append(row)
    return rows
