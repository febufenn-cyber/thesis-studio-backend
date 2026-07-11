"""Durable PostgreSQL job queue and worker.

Jobs are claimed with ``FOR UPDATE SKIP LOCKED`` so multiple workers can be
added later without Redis. The initial deployment runs one worker, which also
serialises memory-heavy LibreOffice conversions on the shared Oracle VM.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.export import Export
from app.models.job import Job
from app.models.manuscript_revision import ManuscriptRevision


log = logging.getLogger(__name__)
POLL_SECONDS = 2.0
HEARTBEAT_SECONDS = 15.0


async def enqueue_job(
    db: AsyncSession,
    *,
    kind: str,
    user_id: UUID,
    project_id: UUID | None,
    payload: dict,
    max_attempts: int = 3,
) -> Job:
    job = Job(
        kind=kind,
        user_id=user_id,
        project_id=project_id,
        payload=payload,
        status="queued",
        max_attempts=max_attempts,
    )
    db.add(job)
    await db.flush()
    return job


async def _claim_next(worker_id: str) -> UUID | None:
    async with AsyncSessionLocal() as db:
        now = datetime.now(timezone.utc)
        job = (
            await db.execute(
                select(Job)
                .where(Job.status == "queued", Job.available_at <= now)
                .order_by(Job.available_at.asc(), Job.created_at.asc())
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
        job.locked_by = worker_id
        job.error_message = None
        await db.commit()
        return job.id


async def _heartbeat(job_id: UUID, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=HEARTBEAT_SECONDS)
        except asyncio.TimeoutError:
            async with AsyncSessionLocal() as db:
                job = (
                    await db.execute(select(Job).where(Job.id == job_id))
                ).scalar_one_or_none()
                if job is None or job.status != "running":
                    return
                job.heartbeat_at = datetime.now(timezone.utc)
                await db.commit()


async def _already_completed(kind: str, payload: dict) -> bool:
    """Return True when a retried job's durable result already exists."""

    async with AsyncSessionLocal() as db:
        if kind == "ingest_manuscript":
            revision = (
                await db.execute(
                    select(ManuscriptRevision).where(
                        ManuscriptRevision.id == UUID(payload["revision_id"])
                    )
                )
            ).scalar_one_or_none()
            return bool(
                revision
                and revision.status == "ready"
                and revision.canonical_snapshot
                and revision.import_report
            )
        if kind == "export":
            export = (
                await db.execute(
                    select(Export).where(Export.id == UUID(payload["export_id"]))
                )
            ).scalar_one_or_none()
            return bool(
                export
                and export.status == "ready"
                and export.storage_key
                and export.checksum
            )
    return False


async def _dispatch(job: Job) -> None:
    payload = job.payload or {}
    if await _already_completed(job.kind, payload):
        log.info("job idempotency hit id=%s kind=%s", job.id, job.kind)
        return
    if job.kind == "ingest_manuscript":
        from app.services.manuscript_service import ingest_revision

        await ingest_revision(
            UUID(payload["revision_id"]),
            UUID(payload["project_id"]),
            UUID(payload["user_id"]),
            apply_when_ready=bool(payload.get("apply_when_ready", True)),
        )
        return
    if job.kind == "export":
        from app.services.export_service import run_export

        await run_export(
            UUID(payload["export_id"]),
            UUID(payload["project_id"]),
            UUID(payload["user_id"]),
        )
        return
    raise ValueError(f"Unknown job kind: {job.kind}")


async def _run_claimed(job_id: UUID) -> None:
    async with AsyncSessionLocal() as db:
        job = (
            await db.execute(select(Job).where(Job.id == job_id))
        ).scalar_one_or_none()
        if job is None:
            return
        detached = Job(
            id=job.id,
            kind=job.kind,
            project_id=job.project_id,
            user_id=job.user_id,
            payload=dict(job.payload or {}),
            status=job.status,
            attempts=job.attempts,
            max_attempts=job.max_attempts,
        )

    stop = asyncio.Event()
    heartbeat = asyncio.create_task(_heartbeat(job_id, stop))
    try:
        await _dispatch(detached)
    except Exception as exc:
        log.exception("job failed id=%s kind=%s", job_id, detached.kind)
        async with AsyncSessionLocal() as db:
            row = (
                await db.execute(select(Job).where(Job.id == job_id))
            ).scalar_one_or_none()
            if row is not None:
                row.error_message = str(exc)[:500]
                row.locked_at = None
                row.locked_by = None
                if row.attempts < row.max_attempts:
                    row.status = "queued"
                    row.available_at = datetime.now(timezone.utc) + timedelta(
                        seconds=min(300, 15 * (2 ** max(row.attempts - 1, 0)))
                    )
                else:
                    row.status = "failed"
                await db.commit()
    else:
        async with AsyncSessionLocal() as db:
            row = (
                await db.execute(select(Job).where(Job.id == job_id))
            ).scalar_one_or_none()
            if row is not None:
                row.status = "succeeded"
                row.locked_at = None
                row.locked_by = None
                row.heartbeat_at = datetime.now(timezone.utc)
                await db.commit()
    finally:
        stop.set()
        await heartbeat


async def recover_stale_jobs(stale_after_minutes: int = 10) -> int:
    """Requeue jobs whose worker stopped heartbeating."""

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=stale_after_minutes)
    async with AsyncSessionLocal() as db:
        rows = list(
            (
                await db.execute(
                    select(Job).where(
                        Job.status == "running",
                        Job.heartbeat_at.is_not(None),
                        Job.heartbeat_at < cutoff,
                    )
                )
            ).scalars()
        )
        for row in rows:
            row.status = "queued" if row.attempts < row.max_attempts else "failed"
            row.available_at = datetime.now(timezone.utc)
            row.locked_at = None
            row.locked_by = None
            row.error_message = "Worker heartbeat expired; job recovered after restart."
        if rows:
            await db.commit()
        return len(rows)


async def worker_loop() -> None:
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    recovered = await recover_stale_jobs()
    if recovered:
        log.warning("recovered %d stale job(s)", recovered)
    log.info("phase1 worker started id=%s", worker_id)
    while True:
        job_id = await _claim_next(worker_id)
        if job_id is None:
            await asyncio.sleep(POLL_SECONDS)
            continue
        await _run_claimed(job_id)


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    asyncio.run(worker_loop())


if __name__ == "__main__":
    main()
