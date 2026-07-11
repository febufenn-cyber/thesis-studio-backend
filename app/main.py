"""FastAPI application entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, update

from app.api import active_registry as active_registry_router
from app.api import ai_partner as ai_partner_router
from app.api import auth as auth_router
from app.api import chat as chat_router
from app.api import citation_schema as citation_schema_router
from app.api import collaboration as collaboration_router
from app.api import collaboration_commands as collaboration_commands_router
from app.api import collaboration_read as collaboration_read_router
from app.api import commercial_billing as commercial_billing_router
from app.api import commercial_operations as commercial_operations_router
from app.api import commercial_privacy as commercial_privacy_router
from app.api import commercial_sessions as commercial_sessions_router
from app.api import compile as compile_router
from app.api import data_portability as data_portability_router
from app.api import editor as editor_router
from app.api import external_downloads as external_downloads_router
from app.api import institutional as institutional_router
from app.api import manuscripts as manuscripts_router
from app.api import presence as presence_router
from app.api import previews as previews_router
from app.api import projects as projects_router
from app.api import resolutions as resolutions_router
from app.api import review_workspace as review_workspace_router
from app.api import sessions as sessions_router
from app.api import submissions as submissions_router
from app.api import support_console as support_console_router
from app.commercial.guards import CommercialGuardMiddleware
from app.commercial.observability import JourneyTracingMiddleware, release_identity
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.services.readiness_service import readiness_report


def _configure_logging() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=settings.LOG_LEVEL,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


async def _sweep_orphaned_compiles() -> None:
    """Mark legacy process-bound compile jobs failed after a restart."""
    from app.db.session import AsyncSessionLocal
    from app.models.file import File

    log = logging.getLogger(__name__)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            update(File)
            .where(File.status == "compiling")
            .values(status="failed", error_message="Server restarted during compile.")
        )
        await db.commit()
        if result.rowcount:
            log.warning("Startup sweep: marked %d legacy compile(s) failed", result.rowcount)


async def _register_release() -> None:
    """Record the exact runtime identity without making deployment success claims."""
    from app.db.session import AsyncSessionLocal
    from app.models.commercial import ReleaseRecord

    identity = release_identity()
    if identity["release_sha"] == "development":
        return
    async with AsyncSessionLocal() as db:
        existing = (
            await db.execute(
                select(ReleaseRecord).where(
                    ReleaseRecord.release_sha == identity["release_sha"]
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            build_time = (
                datetime.fromisoformat(identity["build_time"].replace("Z", "+00:00"))
                if identity["build_time"]
                else datetime.now(timezone.utc)
            )
            db.add(
                ReleaseRecord(
                    release_sha=identity["release_sha"],
                    build_time=build_time,
                    schema_version=identity["schema_version"],
                    renderer_version=identity["renderer_version"],
                    prompt_bundle_version=identity["prompt_bundle_version"],
                    canonical_schema_version=identity["canonical_schema_version"],
                    state="running",
                    metadata_json={"environment": identity["environment"]},
                )
            )
            await db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    _configure_logging()
    log = logging.getLogger(__name__)
    settings = get_settings()
    log.info(
        "Robofox Thesis Studio starting env=%s release=%s schema=%s",
        settings.ENV,
        settings.RELEASE_SHA or "development",
        settings.SCHEMA_VERSION,
    )
    try:
        await _sweep_orphaned_compiles()
    except Exception:
        log.exception("Startup sweep of legacy compiles failed (continuing)")
    try:
        from app.services.job_queue import recover_stale_jobs

        recovered = await recover_stale_jobs()
        if recovered:
            log.warning("Startup recovery released %d expired job lease(s)", recovered)
    except Exception:
        log.exception("Startup recovery of expired jobs failed (continuing)")
    try:
        await _register_release()
    except Exception:
        log.exception("Release identity registration failed (continuing)")
    yield
    log.info("Robofox Thesis Studio shutting down release=%s", settings.RELEASE_SHA or "development")


def _serve_frontend(path: Path, label: str) -> Response:
    if not path.exists():
        return JSONResponse(
            status_code=404,
            content={"detail": f"{label} frontend build not found."},
        )
    return FileResponse(path)


def create_app() -> FastAPI:
    settings = get_settings()
    static_dir = Path(__file__).parent / "static"
    v2_index = static_dir / "v2.html"
    legacy_index = static_dir / "index.html"

    app = FastAPI(
        title="Robofox Thesis Studio API",
        description=(
            "Integrity-first academic manuscript conversion, governed collaboration and AI, "
            "with commercial reliability, recovery, billing and privacy controls."
        ),
        version="0.7.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.DEBUG else None,
        redoc_url=None,
    )
    app.add_middleware(JourneyTracingMiddleware)
    app.add_middleware(CommercialGuardMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "X-Trace-ID", "X-Release-SHA"],
    )
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    app.include_router(auth_router.router)
    app.include_router(commercial_sessions_router.router)
    app.include_router(sessions_router.router)
    app.include_router(chat_router.router)
    app.include_router(compile_router.router)
    app.include_router(projects_router.router)
    app.include_router(manuscripts_router.router)
    app.include_router(resolutions_router.router)
    app.include_router(active_registry_router.router)
    app.include_router(citation_schema_router.router)
    app.include_router(editor_router.router)
    app.include_router(review_workspace_router.router)
    app.include_router(previews_router.router)
    app.include_router(ai_partner_router.router)
    app.include_router(collaboration_router.router)
    app.include_router(collaboration_commands_router.router)
    app.include_router(collaboration_read_router.router)
    app.include_router(presence_router.router)
    app.include_router(institutional_router.router)
    app.include_router(submissions_router.router)
    app.include_router(external_downloads_router.router)
    app.include_router(data_portability_router.router)
    app.include_router(commercial_billing_router.router)
    app.include_router(commercial_operations_router.router)
    app.include_router(commercial_privacy_router.router)
    app.include_router(support_console_router.router)

    @app.get("/healthz", tags=["meta"])
    async def health() -> dict:
        return {
            "status": "ok",
            "frontend": "v2",
            "phase": "commercial_reliability_security_scale",
            "release": release_identity(),
            "component_boundary": {
                "application": "healthy",
                "ai": "reported separately through provider health and /status",
            },
        }

    @app.get("/readyz", tags=["meta"])
    async def ready():
        report = await readiness_report()
        report["release"] = release_identity()
        return JSONResponse(
            status_code=200 if report["status"] == "ready" else 503,
            content=report,
        )

    @app.get("/", include_in_schema=False)
    async def frontend_v2() -> Response:
        return _serve_frontend(v2_index, "v2")

    @app.get("/legacy", include_in_schema=False)
    async def frontend_legacy() -> Response:
        return _serve_frontend(legacy_index, "legacy")

    register_exception_handlers(app)
    return app


app = create_app()
