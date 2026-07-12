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

from app.api import (
    active_registry,
    ai_partner,
    auth,
    chat,
    citation_schema,
    collaboration,
    collaboration_commands,
    collaboration_read,
    collaboration_sources,
    commercial_billing,
    commercial_operations,
    commercial_privacy,
    commercial_reliability,
    commercial_sessions,
    compile,
    data_portability,
    editor,
    external_downloads,
    institutional,
    institutional_lifecycle,
    manuscripts,
    presence,
    previews,
    projects,
    resolutions,
    review_workspace,
    sessions,
    submissions,
    support_console,
)
from app.commercial.guards import CommercialGuardMiddleware
from app.commercial.observability import JourneyTracingMiddleware, release_identity
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.services.readiness_service import readiness_report


API_MODULES = (
    auth,
    commercial_sessions,
    sessions,
    chat,
    compile,
    projects,
    manuscripts,
    resolutions,
    active_registry,
    citation_schema,
    editor,
    review_workspace,
    previews,
    ai_partner,
    collaboration,
    collaboration_commands,
    collaboration_read,
    collaboration_sources,
    presence,
    institutional,
    institutional_lifecycle,
    submissions,
    external_downloads,
    data_portability,
    commercial_billing,
    commercial_operations,
    commercial_privacy,
    commercial_reliability,
    support_console,
)


def _configure_logging() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=settings.LOG_LEVEL,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


async def _sweep_orphaned_compiles() -> None:
    from app.db.session import AsyncSessionLocal
    from app.models.file import File

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            update(File)
            .where(File.status == "compiling")
            .values(status="failed", error_message="Server restarted during compile.")
        )
        await db.commit()
        if result.rowcount:
            logging.getLogger(__name__).warning(
                "Startup sweep: marked %d legacy compile(s) failed", result.rowcount
            )


async def _register_release() -> None:
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
        if existing is not None:
            return
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
    for module in API_MODULES:
        app.include_router(module.router)

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
        return _serve_frontend(static_dir / "v2.html", "v2")

    @app.get("/legacy", include_in_schema=False)
    async def frontend_legacy() -> Response:
        return _serve_frontend(static_dir / "index.html", "legacy")

    register_exception_handlers(app)
    return app


app = create_app()
