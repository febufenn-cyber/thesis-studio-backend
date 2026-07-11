"""AI availability, entitlement, concurrency and provider capacity controls."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.settings import get_ai_settings
from app.ai.task_registry import TaskSpec, model_for
from app.commercial.ai_capacity import (
    AIProviderUnavailable,
    ProviderRoute,
    entitlement_for_task,
    provider_status,
    route_ai_provider,
)
from app.commercial.entitlements import (
    EntitlementContext,
    EntitlementDenied,
    EntitlementQuotaExceeded,
    require_entitlement,
)
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
) -> ProviderRoute:
    settings = get_ai_settings()
    if not settings.global_enabled:
        raise AIUnavailable("Robofox Scholar is disabled globally. Editing and export remain available.")
    if not project.ai_enabled:
        raise AIUnavailable("Robofox Scholar is disabled for this project.")
    policy = project.ai_policy or {}
    allowed = set(policy.get("allowed_modes") or [])
    if allowed and spec.mode not in allowed:
        raise AIUnavailable(f"Task mode {spec.mode!r} is disabled by the project policy.")

    entitlement_key, reset_period = entitlement_for_task(spec.mode)
    try:
        await require_entitlement(
            db,
            EntitlementContext(
                institution_id=project.institution_id,
                user_id=user_id,
                project_id=project.id,
            ),
            entitlement_key,
            reset_period=reset_period,
        )
    except EntitlementDenied as exc:
        raise AIUnavailable(str(exc)) from exc
    except EntitlementQuotaExceeded as exc:
        raise AICapacityExceeded(str(exc)) from exc

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
            "You already have an AI task running. Editing, verification and exports are unaffected."
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
            "Daily AI safety allowance reached. Deterministic workspace features remain available."
        )

    if spec.model_tier == "strong":
        strong_daily = int(
            (
                await db.execute(
                    select(func.count(AIRun.id)).where(
                        AIRun.user_id == user_id,
                        AIRun.created_at >= day_start,
                        AIRun.model == get_settings().CLAUDE_COMPILE_MODEL,
                        AIRun.status.not_in(("cancelled",)),
                    )
                )
            ).scalar_one()
        )
        if strong_daily >= settings.daily_strong_run_limit:
            raise AICapacityExceeded("Daily whole-thesis/deep-review safety allowance reached.")

    try:
        return await route_ai_provider(
            db,
            institution_id=project.institution_id,
            task_mode=spec.mode,
            requested_model=model_for(spec),
        )
    except AIProviderUnavailable as exc:
        raise AIUnavailable(str(exc)) from exc


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
    failures = int(
        (
            await db.execute(
                select(func.count(AIRun.id)).where(
                    AIRun.project_id == project.id,
                    AIRun.status == "failed",
                )
            )
        ).scalar_one()
    )
    providers = await provider_status(db, project.institution_id)
    provider_available = any(
        row["state"] in {"active", "pilot_only"}
        and row["circuit_state"] in {"closed", "half_open"}
        for row in providers
    )
    enabled = settings.global_enabled and project.ai_enabled
    return {
        "enabled": enabled,
        "global_enabled": settings.global_enabled,
        "project_enabled": project.ai_enabled,
        "providers": providers,
        "running_for_user": active,
        "queued_for_project": queued,
        "failed_runs_total": failures,
        "degraded_mode": not enabled or not provider_available,
        "deterministic_workspace_available": True,
        "component_health": {
            "application": "operational",
            "editing": "operational",
            "export": "operational",
            "ai": "operational" if enabled and provider_available else "degraded",
        },
        "limits": {
            "user_concurrent": settings.user_concurrent_limit,
            "project_queue": settings.project_queue_limit,
            "daily_runs": settings.daily_run_limit,
            "daily_strong_runs": settings.daily_strong_run_limit,
        },
    }
