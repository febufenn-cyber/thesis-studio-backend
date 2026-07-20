"""Worker readiness must not fail a fresh deployment (amd64 smoke regression).

The web app enqueues maintenance jobs at boot (retention sweep, notification
digest) seconds before any worker claims them. A freshly-queued job is not
evidence of a missing worker — only a job waiting past the grace window is.
Without this, every clean deployment 503s its own /readyz healthcheck at
startup, exactly as the amd64 container runtime smoke caught.

readiness_report() opens its own sessions, so these tests write COMMITTED
state through the app's real sessionmaker (the conftest db_session rides a
rolled-back transaction another connection can never see) and provision the
alembic_version row that metadata.create_all does not create.
"""

from __future__ import annotations

from typing import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import AsyncSessionLocal, engine as app_engine
from app.services.readiness_service import readiness_report

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def ready_db(test_engine) -> AsyncGenerator[None, None]:
    """Committed alembic_version + clean jobs table, visible to any session."""
    # The app's module-global engine pools connections; pytest gives each test
    # its own event loop, so recycle the pool onto THIS loop first.
    await app_engine.dispose()
    async with AsyncSessionLocal() as s:
        await s.execute(text(
            "CREATE TABLE IF NOT EXISTS alembic_version "
            "(version_num varchar(32) PRIMARY KEY)"
        ))
        await s.execute(text("DELETE FROM alembic_version"))
        await s.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:v)"),
            {"v": get_settings().SCHEMA_VERSION},
        )
        await s.execute(text("DELETE FROM jobs"))
        await s.commit()
    yield
    async with AsyncSessionLocal() as s:
        await s.execute(text("DELETE FROM jobs"))
        await s.commit()
    await app_engine.dispose()


async def _enqueue(kind: str, *, minutes_old: int = 0, status: str = "queued",
                   heartbeat_now: bool = False) -> None:
    async with AsyncSessionLocal() as s:
        await s.execute(text(
            "INSERT INTO jobs (id, kind, queue_name, status, payload, result, priority, "
            " attempts, max_attempts, available_at, created_at, updated_at, heartbeat_at) "
            "VALUES (gen_random_uuid(), :kind, 'maintenance', :status, '{}'::jsonb, '{}'::jsonb, 100, "
            " 0, 5, now(), now() - make_interval(mins => :age), now(), "
            " CASE WHEN :beat THEN now() ELSE NULL END)"
        ), {"kind": kind, "status": status, "age": minutes_old, "beat": heartbeat_now})
        await s.commit()


async def _worker_check() -> dict:
    report = await readiness_report()
    worker = report["checks"]["worker"]
    assert "queued" in worker, f"worker check collapsed: {report['checks']}"
    return worker


async def test_fresh_boot_jobs_do_not_fail_readiness(ready_db) -> None:
    """Jobs enqueued moments ago (boot-time maintenance) leave worker ok."""
    await _enqueue("retention_sweep")
    await _enqueue("notification_digest")
    worker = await _worker_check()
    assert worker["queued"] == 2
    assert worker["queued_waiting"] == 0
    assert worker["ok"] is True


async def test_stale_queue_without_worker_still_fails(ready_db) -> None:
    """A job waiting past the grace window with no heartbeat = worker down."""
    await _enqueue("retention_sweep", minutes_old=30)
    worker = await _worker_check()
    assert worker["queued_waiting"] == 1
    assert worker["ok"] is False


async def test_stale_queue_with_live_heartbeat_is_ok(ready_db) -> None:
    """Old queue + a worker heartbeating = busy, not broken."""
    await _enqueue("retention_sweep", minutes_old=30)
    await _enqueue("notification_digest", status="running", heartbeat_now=True)
    worker = await _worker_check()
    assert worker["queued_waiting"] == 1
    assert worker["ok"] is True
