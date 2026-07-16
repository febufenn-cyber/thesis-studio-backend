"""Daily retention-sweep scheduling.

``execute_retention_sweep`` (app/commercial/privacy.py) enforces per-institution
retention policies, but until now nothing ever enqueued it — the compliance
mechanism existed and never ran. This module closes that gap:

- ``enqueue_daily_retention_sweep()`` enqueues one ``retention_sweep`` job for
  the current UTC date, deduplicated by idempotency key, so any number of web
  replicas calling it (or repeated startups) still yield exactly one sweep/day.
- ``retention_scheduler_loop()`` runs in the web process's lifespan and calls
  the enqueue roughly hourly — cheap, because dedup makes extra calls no-ops.

The job itself executes on the queue worker (worker_loop), inheriting its
leasing, retries and recovery.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from app.core.config import get_settings

log = logging.getLogger(__name__)

_CHECK_INTERVAL_SECONDS = 3600.0


async def enqueue_daily_retention_sweep() -> bool:
    """Enqueue today's sweep (all institutions). True if a new job was created."""
    from app.db.session import AsyncSessionLocal
    from app.services.job_queue import enqueue_job

    today = datetime.now(UTC).date().isoformat()
    key = f"retention-sweep-{today}"
    async with AsyncSessionLocal() as db:
        job = await enqueue_job(
            db,
            kind="retention_sweep",
            user_id=None,  # system-scheduled
            project_id=None,
            payload={"scheduled_for": today},
            idempotency_key=key,
        )
        created = job.status == "queued" and job.attempts == 0 and (
            job.idempotency_key == key
        )
        await db.commit()
    return created


async def enqueue_daily_digest() -> bool:
    """Enqueue today's notification digest job. True if newly created."""
    from app.db.session import AsyncSessionLocal
    from app.services.job_queue import enqueue_job

    today = datetime.now(UTC).date().isoformat()
    key = f"notification-digest-{today}"
    async with AsyncSessionLocal() as db:
        job = await enqueue_job(
            db,
            kind="notification_digest",
            user_id=None,
            project_id=None,
            payload={"scheduled_for": today},
            idempotency_key=key,
        )
        created = job.status == "queued" and job.attempts == 0 and (
            job.idempotency_key == key
        )
        await db.commit()
    return created


async def retention_scheduler_loop() -> None:
    """Hourly tick: make sure today's sweep exists. Cancelled at shutdown."""
    if not getattr(get_settings(), "RETENTION_SWEEP_ENABLED", True):
        log.info("Retention sweep scheduling disabled by RETENTION_SWEEP_ENABLED")
        return
    while True:
        try:
            created = await enqueue_daily_retention_sweep()
            if created:
                log.info("Enqueued daily retention sweep")
            if getattr(get_settings(), "DIGEST_EMAILS_ENABLED", True):
                if await enqueue_daily_digest():
                    log.info("Enqueued daily notification digest")
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Retention sweep enqueue failed (will retry next tick)")
        await asyncio.sleep(_CHECK_INTERVAL_SECONDS)
