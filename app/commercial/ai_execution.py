"""Commercial execution wrapper for grounded AI jobs."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select

from app.ai.adapters import provider_for_route
from app.ai.orchestrator import run_grounded_ai
from app.ai.task_registry import get_task, model_for
from app.commercial.ai_capacity import (
    entitlement_for_task,
    record_provider_failure,
    record_provider_success,
    route_ai_provider,
)
from app.commercial.entitlements import EntitlementContext, record_usage
from app.db.session import AsyncSessionLocal
from app.models.ai_run import AIRun
from app.models.project import Project


async def execute_ai_job(run_id: UUID) -> None:
    route = None
    project = None
    run = None
    async with AsyncSessionLocal() as db:
        run = (
            await db.execute(select(AIRun).where(AIRun.id == run_id))
        ).scalar_one_or_none()
        if run is None:
            raise ValueError("AI run no longer exists")
        project = (
            await db.execute(select(Project).where(Project.id == run.project_id))
        ).scalar_one_or_none()
        if project is None:
            raise ValueError("AI project no longer exists")
        now = datetime.now(timezone.utc)
        if run.queue_deadline_at is not None and run.queue_deadline_at <= now:
            run.status = "failed"
            run.error_message = "AI queue deadline elapsed before provider capacity became available."
            run.completed_at = now
            run.progress = {
                "stage": "failed",
                "message": run.error_message,
                "retryable": False,
            }
            await db.commit()
            return
        spec = get_task(run.task_mode)
        route = await route_ai_provider(
            db,
            institution_id=project.institution_id,
            task_mode=run.task_mode,
            requested_model=model_for(spec),
        )
        run.provider_id = route.provider_id
        run.provider_slug = route.slug
        run.provider_adapter = route.adapter
        run.model = route.model
        run.progress = {
            **(run.progress or {}),
            "provider": route.slug,
            "provider_adapter": route.adapter,
            "message": "Waiting for healthy provider capacity.",
        }
        await db.commit()

    provider = provider_for_route(route)
    started = time.monotonic()
    try:
        await run_grounded_ai(run_id, provider=provider)
    except Exception as exc:
        async with AsyncSessionLocal() as db:
            await record_provider_failure(db, route, error_class=type(exc).__name__)
            await db.commit()
        raise
    else:
        latency_ms = int((time.monotonic() - started) * 1000)
        async with AsyncSessionLocal() as db:
            refreshed_run = (
                await db.execute(select(AIRun).where(AIRun.id == run_id))
            ).scalar_one()
            refreshed_project = (
                await db.execute(select(Project).where(Project.id == refreshed_run.project_id))
            ).scalar_one()
            await record_provider_success(db, route, latency_ms=latency_ms)
            if refreshed_run.status == "succeeded":
                key, reset_period = entitlement_for_task(refreshed_run.task_mode)
                await record_usage(
                    db,
                    EntitlementContext(
                        institution_id=refreshed_project.institution_id,
                        user_id=refreshed_run.user_id,
                        project_id=refreshed_project.id,
                    ),
                    key,
                    operation=refreshed_run.task_mode,
                    reset_period=reset_period or "month",
                    idempotency_key=f"ai-run:{refreshed_run.id}",
                    metadata={
                        "provider": route.slug,
                        "adapter": route.adapter,
                        "model": refreshed_run.model,
                        "latency_ms": latency_ms,
                    },
                )
            await db.commit()
