"""Tenant/user feature rollout resolution for progressive delivery."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.commercial import FeatureFlag, RolloutAssignment


async def feature_enabled(
    db: AsyncSession,
    key: str,
    *,
    institution_id: UUID | None,
    user_id: UUID | None,
) -> bool:
    flag = (
        await db.execute(
            select(FeatureFlag).where(
                FeatureFlag.key == key,
                FeatureFlag.state == "active",
            )
        )
    ).scalar_one_or_none()
    if flag is None:
        return False
    now = datetime.now(timezone.utc)
    scopes = [
        and_(
            RolloutAssignment.institution_id.is_(None),
            RolloutAssignment.user_id.is_(None),
        )
    ]
    if institution_id is not None:
        scopes.append(
            and_(
                RolloutAssignment.institution_id == institution_id,
                RolloutAssignment.user_id.is_(None),
            )
        )
    if user_id is not None:
        scopes.append(
            and_(
                RolloutAssignment.user_id == user_id,
                or_(
                    RolloutAssignment.institution_id.is_(None),
                    RolloutAssignment.institution_id == institution_id,
                ),
            )
        )
    assignments = list(
        (
            await db.execute(
                select(RolloutAssignment).where(
                    RolloutAssignment.feature_flag_id == flag.id,
                    or_(RolloutAssignment.starts_at.is_(None), RolloutAssignment.starts_at <= now),
                    or_(RolloutAssignment.ends_at.is_(None), RolloutAssignment.ends_at > now),
                    or_(*scopes),
                )
            )
        ).scalars()
    )
    assignments.sort(
        key=lambda row: (
            2 if row.user_id is not None else 1 if row.institution_id is not None else 0,
            row.created_at,
        )
    )
    return assignments[-1].enabled if assignments else flag.default_enabled
