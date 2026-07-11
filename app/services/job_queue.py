"""Durable PostgreSQL queue for independently replaceable worker processes."""

from __future__ import annotations

import asyncio
import logging
import os
import socket
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.models.ai_run import AIRun
from app.models.document_preview import DocumentPreview
from app.models.export import Export
from app.models.job import Job
from app.models.manuscript_revision import ManuscriptRevision


log = logging.getLogger(__name__)
POLL_SECONDS = 2.0

_QUEUE_BY_KIND = {
    "ingest_manuscript": "general",
    "verify_project": "general",
    "ai_run": "ai",
    "preview": "pdf",
    "export": "pdf",
    "billing_event": "maintenance",
    "data_lifecycle": "maintenance",
    "retention_sweep": "maintenance",
}


async def enqueue_job(
    db: AsyncSession,
    *,
    kind: str,
    user_id: UUID,
    project_id: UUID | None,
    payload: dict,
    max_attempts: int = 3,
    queue_name: str | None = None,
    priority: int = 100,
    deadline_at: datetime | None = None,
    idempotency_key: str | None = None,
) -> Job:
    if idempotency_key:
        existing = (
            await db.execute(select(Job).where(Job.idempotency_key == idempotency_key))
        ).scalar_one_or_none()
        if existing is not None:
            return existing
    job = Job(
        kind=kind,
        queue_name=queue_name or _QUEUE_BY_KIND.get(kind, "general"),
        priority=priority,
        user_id=user_id,
        project_id=project_id,
        payload=payload,
        status="queued",
        max_attempts=max_attempts,
        deadline_at=deadline_at,
        idempotency_key=idempotency_key,
        release_sha=get_settings().RELEASE_SHA or None,
    )
    db.add(job)
    await db.flush()
    return job


async def _expire_deadlines(db: AsyncSession, now: datetime) -> int:
    rows = list(
        (
            await db.execute(
                select(Job).where(
                    Job.status == "queued",
                    Job.deadline_at.is_not(None),
                    Job.deadline_at <= now,
                )
            )
        ).scalars()
    )
    for row in rows:
        row.status = "failed"
        row.error_message = "Queue deadline elapsed before a compatible worker claimed the job."
        row.result = {"deadline_elapsed": True}
    return len(rows)


async def _recover_expired_leases(db: AsyncSession, now: datetime) -> int:
    rows = list(
        (
            await db.execute(
                select(Job).where(
                    Job.status == "running",
                    Job.lease_expires_at.is_not(None),
                    Job.lease_expires_at <= now,
                )
            )
        ).scalars()
    )
    for row in rows:
        row.status = "queued" if row.attempts < row.max_attempts else "failed"
        row.available_at = now
        row.locked_at = None
        row.locked_by = None
        row.lease_expires_at = None
        row.error_message = "Worker lease expired; operation was released for idempotent retry."
    return len(rows)


async def _claim_next(worker_id: str, queues: set[str]) -> UUID | None:
    settings = get_settings()
    async with AsyncSessionLocal() as db:
        now = datetime.now(timezone.utc)
        changed = await _recover_expired_leases(db, now) + await _expire_deadlines(db, now)
        if changed:
            await db.commit()
        job = (
            await db.execute(
                select(Job)
                .where(
                    Job.status == "queued",
                    Job.available_at <= now,
                    Job.queue_name.in_(queues),
                    or_(Job.deadline_at.is_(None), Job.deadline_at > now),
                )
                .order_by(Job.priority.asc(), Job.available_at.asc(), Job.created_at.asc())
                .with_for_update(skip_locked=True)
                .limit(1)
            )
        ).scalar_one_or_none()
        if job is None:
            return None
        job.status = "running"
        job.attempts += 1
        job.locked_at = now
        job.heartbeat_at = now
        job.lease_expires_at = now + timedelta(seconds=settings.JOB_LEASE_SECONDS)
        job.locked_by = worker_id
        job.error_message = None
        await db.commit()
        return job.id


async def _heartbeat(job_id: UUID, worker_id: str, stop: asyncio.Event) -> None:
    settings = get_settings()
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.JOB_HEARTBEAT_SECONDS)
        except asyncio.TimeoutError:
            async with AsyncSessionLocal() as db:
                row = (
                    await db.execute(
                        select(Job).where(
                            Job.id == job_id,
                            Job.status == "running",
                            Job.locked_by == worker_id,
                        )
                    )
                ).scalar_one_or_none()
                if row is None:
                    return
                now = datetime.now(timezone.utc)
                row.heartbeat_at = now
                row.lease_expires_at = now + timedelta(seconds=settings.JOB_LEASE_SECONDS)
                await db.commit()


async def _already_completed(kind: str, payload: dict) -> bool:
    async with AsyncSessionLocal() as db:
        if kind == "ingest_manuscript":
            row = (
                await db.execute(
                    select(ManuscriptRevision).where(
                        ManuscriptRevision.id == UUID(payload["revision_id"])
                    )
                )
            ).scalar_one_or_none()
            return bool(row and row.status == "ready" and row.canonical_snapshot and row.import_report)
        if kind == "export":
            row = (
                await db.execute(select(Export).where(Export.id == UUID(payload["export_id"])))
            ).scalar_one_or_none()
            return bool(row and row.status == "ready" and row.storage_key and row.checksum)
        if kind == "preview":
            row = (
                await db.execute(
                    select(DocumentPreview).where(
                        DocumentPreview.id == UUID(payload["preview_id"])
                    )
                )
            ).scalar_one_or_none()
            return bool(row and row.status == "ready" and row.storage_key and row.checksum)
        if kind == "ai_run":
            row = (
                await db.execute(select(AIRun).where(AIRun.id == UUID(payload["run_id"])))
            ).scalar_one_or_none()
            return bool(row and row.status in {"succeeded", "cancelled", "stale"})
    return False


async def _dispatch(job: Job) -> dict:
    payload = job.payload or {}
    if await _already_completed(job.kind, payload):
        return {"idempotency_hit": True}
    if job.kind == "ingest_manuscript":
        from app.services.manuscript_service import ingest_revision

        await ingest_revision(
            UUID(payload["revision_id"]),
            UUID(payload["project_id"]),
            UUID(payload["user_id"]),
            apply_when_ready=bool(payload.get("apply_when_ready", True)),
        )
        return {"revision_id": payload["revision_id"]}
    if job.kind == "export":
        from app.services.export_service import run_export

        await run_export(
            UUID(payload["export_id"]),
            UUID(payload["project_id"]),
            UUID(payload["user_id"]),
        )
        return {"export_id": payload["export_id"]}
    if job.kind == "preview":
        from app.services.preview_service import run_preview

        await run_preview(
            UUID(payload["preview_id"]),
            UUID(payload["project_id"]),
            UUID(payload["user_id"]),
        )
        return {"preview_id": payload["preview_id"]}
    if job.kind == "ai_run":
        from app.commercial.ai_execution import execute_ai_job

        await execute_ai_job(UUID(payload["run_id"]))
        return {"run_id": payload["run_id"]}
    if job.kind == "billing_event":
        from app.commercial.billing import replay_event

        async with AsyncSessionLocal() as db:
            row = await replay_event(db, UUID(payload["billing_event_id"]))
            return {"billing_event_id": str(row.id), "state": row.state}
    if job.kind in {"data_lifecycle", "retention_sweep"}:
        from app.commercial.privacy import execute_lifecycle_job, execute_retention_sweep

        if job.kind == "data_lifecycle":
            return await execute_lifecycle_job(UUID(payload["request_id"]))
        return await execute_retention_sweep(payload)
    raise ValueError(f"Unknown job kind: {job.kind}")


async def _run_claimed(job_id: UUID, worker_id: str) -> None:
    async with AsyncSessionLocal() as db:
        row = (await db.execute(select(Job).where(Job.id == job_id))).scalar_one_or_none()
        if row is None or row.locked_by != worker_id:
            return
        detached = Job(
            id=row.id,
            kind=row.kind,
            queue_name=row.queue_name,
            priority=row.priority,
            project_id=row.project_id,
            user_id=row.user_id,
            payload=dict(row.payload or {}),
            status=row.status,
            attempts=row.attempts,
            max_attempts=row.max_attempts,
            deadline_at=row.deadline_at,
            idempotency_key=row.idempotency_key,
            release_sha=row.release_sha,
        )

    stop = asyncio.Event()
    heartbeat = asyncio.create_task(_heartbeat(job_id, worker_id, stop))
    try:
        result = await _dispatch(detached)
    except Exception as exc:
        log.exception("job failed id=%s kind=%s queue=%s", job_id, detached.kind, detached.queue_name)
        async with AsyncSessionLocal() as db:
            row = (await db.execute(select(Job).where(Job.id == job_id))).scalar_one_or_none()
            if row is not None and row.locked_by == worker_id:
                row.error_message = str(exc)[:500]
                row.locked_at = None
                row.locked_by = None
                row.lease_expires_at = None
                now = datetime.now(timezone.utc)
                deadline_open = row.deadline_at is None or row.deadline_at > now
                if row.attempts < row.max_attempts and deadline_open:
                    row.status = "queued"
                    row.available_at = now + timedelta(
                        seconds=min(300, 15 * (2 ** max(row.attempts - 1, 0)))
                    )
                else:
                    row.status = "failed"
                await db.commit()
    else:
        async with AsyncSessionLocal() as db:
            row = (await db.execute(select(Job).where(Job.id == job_id))).scalar_one_or_none()
            if row is not None and row.locked_by == worker_id:
                row.status = "succeeded"
                row.result = result or {}
                row.locked_at = None
                row.locked_by = None
                row.lease_expires_at = None
                row.heartbeat_at = datetime.now(timezone.utc)
                await db.commit()
    finally:
        stop.set()
        await heartbeat


async def recover_stale_jobs() -> int:
    async with AsyncSessionLocal() as db:
        count = await _recover_expired_leases(db, datetime.now(timezone.utc))
        if count:
            await db.commit()
        return count


def configured_queues() -> set[str]:
    raw = get_settings().WORKER_QUEUE or "general"
    return {item.strip() for item in raw.split(",") if item.strip()}


async def worker_loop() -> None:
    settings = get_settings()
    worker_id = settings.WORKER_ID or f"{socket.gethostname()}:{os.getpid()}"
    queues = configured_queues()
    recovered = await recover_stale_jobs()
    if recovered:
        log.warning("recovered %d expired worker lease(s)", recovered)
    log.info("thesis worker started id=%s queues=%s release=%s", worker_id, sorted(queues), settings.RELEASE_SHA)
    while True:
        job_id = await _claim_next(worker_id, queues)
        if job_id is None:
            await asyncio.sleep(POLL_SECONDS)
            continue
        await _run_claimed(job_id, worker_id)


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    asyncio.run(worker_loop())


if __name__ == "__main__":
    main()
