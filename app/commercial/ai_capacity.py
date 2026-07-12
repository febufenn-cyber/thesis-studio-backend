"""Provider-independent AI routing, health and circuit-breaker controls."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.ai_run import AIRun
from app.models.commercial import AIProvider, AIProviderHealth


class AIProviderUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class ProviderRoute:
    provider_id: UUID | None
    slug: str
    adapter: str
    model: str
    credential_reference: str | None
    max_concurrency: int
    synthetic: bool = False


def entitlement_for_task(task_mode: str) -> tuple[str, str | None]:
    if task_mode in {"coherence", "memory_refresh"}:
        return "ai.whole_thesis_review.monthly", "month"
    if task_mode in {"diagnose", "plan", "challenge", "research", "viva"}:
        return "ai.chapter_review.monthly", "month"
    return "ai.chat", None


def _legacy_cli_available() -> bool:
    configured = get_settings().CLAUDE_CLI_PATH
    return bool(shutil.which(configured) or (configured.startswith("/") and os.path.exists(configured)))


async def _health(db: AsyncSession, provider: AIProvider) -> AIProviderHealth:
    row = (
        await db.execute(
            select(AIProviderHealth).where(AIProviderHealth.provider_id == provider.id)
        )
    ).scalar_one_or_none()
    if row is None:
        row = AIProviderHealth(provider_id=provider.id)
        db.add(row)
        await db.flush()
    return row


async def route_ai_provider(
    db: AsyncSession,
    *,
    institution_id: UUID | None,
    task_mode: str,
    requested_model: str,
) -> ProviderRoute:
    settings = get_settings()
    if settings.AI_GLOBAL_EMERGENCY_THROTTLE:
        raise AIProviderUnavailable(
            "AI assistance is temporarily throttled. Editing, review, verification and export remain available."
        )
    now = datetime.now(timezone.utc)
    providers = list(
        (
            await db.execute(
                select(AIProvider)
                .where(
                    AIProvider.state == "active",
                    or_(
                        AIProvider.institution_id.is_(None),
                        AIProvider.institution_id == institution_id,
                    ),
                )
                .order_by(
                    AIProvider.institution_id.desc().nullslast(),
                    AIProvider.priority.asc(),
                    AIProvider.created_at.asc(),
                )
            )
        ).scalars()
    )
    for provider in providers:
        supported = set(provider.supported_tasks or [])
        if supported and task_mode not in supported:
            continue
        health = await _health(db, provider)
        if health.circuit_state == "open":
            if health.retry_after is None or health.retry_after > now:
                continue
            health.circuit_state = "half_open"
        running = int(
            (
                await db.execute(
                    select(func.count(AIRun.id)).where(
                        AIRun.provider_id == provider.id,
                        AIRun.status == "running",
                    )
                )
            ).scalar_one()
        )
        if running >= provider.max_concurrency:
            continue
        model = str((provider.model_routes or {}).get(task_mode) or requested_model)
        return ProviderRoute(
            provider_id=provider.id,
            slug=provider.slug,
            adapter=provider.adapter,
            model=model,
            credential_reference=provider.credential_reference,
            max_concurrency=provider.max_concurrency,
        )

    # Development keeps the historical synthetic pilot route so tests and local
    # demos can replace the provider in-process without requiring a real CLI
    # binary. Staging/production never receive this synthetic route: they must
    # configure a healthy provider or have an explicitly available pilot CLI.
    if _legacy_cli_available() or settings.ENV == "development":
        return ProviderRoute(
            provider_id=None,
            slug="legacy-claude-cli",
            adapter="claude_cli",
            model=requested_model,
            credential_reference=None,
            max_concurrency=1,
            synthetic=True,
        )
    raise AIProviderUnavailable(
        "No healthy AI provider is available. The request may remain queued; deterministic workspace features are healthy."
    )


async def record_provider_success(
    db: AsyncSession,
    route: ProviderRoute,
    *,
    latency_ms: int | None = None,
) -> None:
    if route.provider_id is None:
        return
    provider = (
        await db.execute(select(AIProvider).where(AIProvider.id == route.provider_id))
    ).scalar_one_or_none()
    if provider is None:
        return
    health = await _health(db, provider)
    health.circuit_state = "closed"
    health.consecutive_failures = 0
    health.retry_after = None
    health.last_success_at = datetime.now(timezone.utc)
    health.latency_ms = latency_ms
    health.last_error_class = None
    await db.flush()


async def record_provider_failure(
    db: AsyncSession,
    route: ProviderRoute,
    *,
    error_class: str,
) -> None:
    if route.provider_id is None:
        return
    provider = (
        await db.execute(select(AIProvider).where(AIProvider.id == route.provider_id))
    ).scalar_one_or_none()
    if provider is None:
        return
    health = await _health(db, provider)
    health.consecutive_failures += 1
    health.last_failure_at = datetime.now(timezone.utc)
    health.last_error_class = error_class[:100]
    if health.consecutive_failures >= get_settings().AI_PROVIDER_FAILURE_THRESHOLD:
        health.circuit_state = "open"
        health.opened_at = health.last_failure_at
        health.retry_after = health.last_failure_at + timedelta(
            seconds=get_settings().AI_CIRCUIT_COOLDOWN_SECONDS
        )
    await db.flush()


async def provider_status(db: AsyncSession, institution_id: UUID | None) -> list[dict]:
    providers = list(
        (
            await db.execute(
                select(AIProvider).where(
                    or_(AIProvider.institution_id.is_(None), AIProvider.institution_id == institution_id)
                )
            )
        ).scalars()
    )
    rows = []
    for provider in providers:
        health = await _health(db, provider)
        rows.append(
            {
                "slug": provider.slug,
                "adapter": provider.adapter,
                "state": provider.state,
                "circuit_state": health.circuit_state,
                "consecutive_failures": health.consecutive_failures,
                "retry_after": health.retry_after,
                "last_success_at": health.last_success_at,
                "last_failure_at": health.last_failure_at,
                "latency_ms": health.latency_ms,
                "credential_configured": bool(provider.credential_reference),
            }
        )
    if not providers:
        available = _legacy_cli_available() or get_settings().ENV == "development"
        rows.append(
            {
                "slug": "legacy-claude-cli",
                "adapter": "claude_cli",
                "state": "pilot_only",
                "circuit_state": "closed" if available else "unavailable",
                "consecutive_failures": None,
                "retry_after": None,
                "last_success_at": None,
                "last_failure_at": None,
                "latency_ms": None,
                "credential_configured": _legacy_cli_available(),
            }
        )
    return rows
