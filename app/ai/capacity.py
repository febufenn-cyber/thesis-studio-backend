"""Application-level AI availability, concurrency and daily capacity controls."""

from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.settings import get_ai_settings
from app.ai.task_registry import TaskSpec
from app.core.config import get_settings
from app.models.ai_run import AIRun
from app.models.project import Project


class AIUnavailable(RuntimeError):
    pass


class AICapacityExceeded(RuntimeError):
    pass


async def enforce_capacity(
    db: AsyncSession,
    project: Project,
    user_id: UUID,
    spec: TaskSpec,
) -> None:
    settings = get_ai_settings()
    if not settings.global_enabled:
        raise AIUnavailable("Robofox Scholar is disabled globally. Editing and export remain available.")
    if not project.ai_enabled:
        raise AIUnavailable("Robofox Scholar is disabled for this project.")
    policy = project.ai_policy or {}
    allowed = set(policy.get("allowed_modes") or [])
    if allowed and spec.mode not in allowed:
        raise AIUnavailable(f"Task mode {spec.mode!r} is disabled by the project policy.")

    active_user = int(
        (
            await db.execute(
                select(func.count(AIRun.id)).where(
                    AIRun.user_id == user_id,
                    AIRun.status == "running",
                )
            )
        ).scalar_one()
    )
    if active_user >= settings.user_concurrent_limit:
        raise AICapacityExceeded(
            "You already have an AI task running. Existing editing, verification and exports are unaffected."
        )

    queued_project = int(
        (
            await db.execute(
                select(func.count(AIRun.id)).where(
                    AIRun.project_id == project.id,
                    AIRun.status.in_(("queued", "running")),
                )
            )
        ).scalar_one()
    )
    if queued_project >= settings.project_queue_limit:
        raise AICapacityExceeded("This project already has the maximum number of queued AI tasks.")

    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    daily = int(
        (
            await db.execute(
                select(func.count(AIRun.id)).where(
                    AIRun.user_id == user_id,
                    AIRun.created_at >= day_start,
                    AIRun.status.not_in(("cancelled",)),
                )
            )
        ).scalar_one()
    )
    if daily >= settings.daily_run_limit:
        raise AICapacityExceeded(
            "Daily AI task allowance reached. Deterministic workspace features remain available."
        )

    if spec.model_tier == "strong":
        strong_models = {get_settings().CLAUDE_COMPILE_MODEL}
        strong_daily = int(
            (
                await db.execute(
                    select(func.count(AIRun.id)).where(
                        AIRun.user_id == user_id,
                        AIRun.created_at >= day_start,
                        AIRun.model.in_(strong_models),
                        AIRun.status.not_in(("cancelled",)),
                    )
                )
            ).scalar_one()
        )
        if strong_daily >= settings.daily_strong_run_limit:
            raise AICapacityExceeded("Daily whole-thesis/deep-review allowance reached.")


def provider_cli_available() -> bool:
    configured = get_settings().CLAUDE_CLI_PATH
    return bool(shutil.which(configured) or (configured.startswith("/") and os.path.exists(configured)))


async def health_snapshot(db: AsyncSession, project: Project, user_id: UUID) -> dict:
    settings = get_ai_settings()
    active = int(
        (
            await db.execute(
                select(func.count(AIRun.id)).where(
                    AIRun.user_id == user_id,
                    AIRun.status == "running",
                )
            )
        ).scalar_one()
    )
    queued = int(
        (
            await db.execute(
                select(func.count(AIRun.id)).where(
                    AIRun.project_id == project.id,
                    AIRun.status == "queued",
                )
            )
        ).scalar_one()
    )
    recent_failures = int(
        (
            await db.execute(
                select(func.count(AIRun.id)).where(
                    AIRun.project_id == project.id,
                    AIRun.status == "failed",
                )
            )
        ).scalar_one()
    )
    enabled = settings.global_enabled and project.ai_enabled
    provider_available = provider_cli_available()
    return {
        "enabled": enabled,
        "global_enabled": settings.global_enabled,
        "project_enabled": project.ai_enabled,
        "provider_cli_available": provider_available,
        "running_for_user": active,
        "queued_for_project": queued,
        "failed_runs_total": recent_failures,
        "degraded_mode": not enabled or not provider_available,
        "deterministic_workspace_available": True,
        "limits": {
            "user_concurrent": settings.user_concurrent_limit,
            "project_queue": settings.project_queue_limit,
            "daily_runs": settings.daily_run_limit,
            "daily_strong_runs": settings.daily_strong_run_limit,
        },
    }
