"""Safe readiness diagnostics for production probes."""

from __future__ import annotations

import os
import shutil
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, text

from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.models.job import Job
from app.renderers.pdf_renderer import check_pdf_stack
from app.services.malware_service import malware_scanner_ready


MIN_FREE_DISK_BYTES = 500 * 1024 * 1024


async def readiness_report() -> dict:
    settings = get_settings()
    checks: dict[str, dict] = {}

    try:
        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
            checks["database"] = {"ok": True}
            migration = (
                await db.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
            ).scalar_one_or_none()
            checks["migration"] = {
                "ok": migration == settings.SCHEMA_VERSION,
                "current": migration,
                "expected": settings.SCHEMA_VERSION,
            }
            now = datetime.now(timezone.utc)
            queued = (
                await db.execute(
                    select(func.count()).select_from(Job).where(Job.status == "queued")
                )
            ).scalar_one()
            running = (
                await db.execute(
                    select(func.count()).select_from(Job).where(Job.status == "running")
                )
            ).scalar_one()
            stuck = (
                await db.execute(
                    select(func.count())
                    .select_from(Job)
                    .where(
                        Job.status == "running",
                        Job.heartbeat_at < now - timedelta(minutes=10),
                    )
                )
            ).scalar_one()
            recent_heartbeat = (
                await db.execute(select(func.max(Job.heartbeat_at)))
            ).scalar_one()
            worker_ok = stuck == 0 and (
                queued == 0
                or (
                    recent_heartbeat is not None
                    and recent_heartbeat >= now - timedelta(minutes=2)
                )
            )
            checks["worker"] = {
                "ok": worker_ok,
                "queued": queued,
                "running": running,
                "stuck": stuck,
                "recent_heartbeat": recent_heartbeat.isoformat() if recent_heartbeat else None,
            }
    except Exception as exc:
        checks["database"] = {"ok": False, "error": type(exc).__name__}
        checks["migration"] = {"ok": False, "expected": settings.SCHEMA_VERSION}
        checks["worker"] = {"ok": False}

    pdf = check_pdf_stack()
    checks["pdf_stack"] = {
        "ok": bool(pdf["soffice"] and pdf["times_new_roman"]),
        **pdf,
    }

    if settings.STORAGE_BACKEND == "r2" or (
        settings.STORAGE_BACKEND == "auto" and settings.R2_ACCOUNT_ID
    ):
        configured = all(
            value and "replace_me" not in value.lower()
            for value in (
                settings.R2_ACCOUNT_ID,
                settings.R2_ACCESS_KEY_ID,
                settings.R2_SECRET_ACCESS_KEY,
                settings.R2_BUCKET_NAME,
            )
        )
        checks["storage"] = {"ok": configured, "backend": "r2"}
    else:
        try:
            root = os.path.abspath(settings.LOCAL_STORAGE_DIR)
            os.makedirs(root, exist_ok=True)
            writable = os.access(root, os.W_OK)
            free = shutil.disk_usage(root).free
            checks["storage"] = {
                "ok": writable and free >= MIN_FREE_DISK_BYTES,
                "backend": "local",
                "free_bytes": free,
            }
        except Exception as exc:
            checks["storage"] = {
                "ok": False,
                "backend": "local",
                "error": type(exc).__name__,
            }

    checks["email"] = {
        "ok": bool(settings.RESEND_API_KEY) or settings.ENV == "development",
        "configured": bool(settings.RESEND_API_KEY),
    }
    checks["malware_scanner"] = await malware_scanner_ready()
    overall = all(check.get("ok", False) for check in checks.values())
    return {
        "status": "ready" if overall else "not_ready",
        "checks": checks,
        "schema_version": settings.SCHEMA_VERSION,
    }
