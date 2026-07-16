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
    api_keys,
    auth,
    bibliography,
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
    deposits,
    domain_profiles,
    editor,
    external_downloads,
    guide,
    institutional,
    institutional_lifecycle,
    integrity,
    interchange,
    interop_pandoc,
    locales,
    manuscripts,
    presence,
    previews,
    projects,
    provenance,
    quote_verification,
    references_import,
    references_resolve,
    references_search,
    source_trust,
    identity,
    copilot,
    research,
    resolutions,
    review_workspace,
    sessions,
    submission_pack,
    submissions,
    supervision,
    support_console,
    writing,
)
from app.commercial.guards import CommercialGuardMiddleware
from app.commercial.observability import JourneyTracingMiddleware, release_identity
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.rate_limit import limiter
from app.services.readiness_service import readiness_report


API_MODULES = (
    auth,
    commercial_sessions,
    sessions,
    chat,
    compile,
    projects,
    references_import,
    references_resolve,
    references_search,
    source_trust,
    identity,
    copilot,
    bibliography,
    writing,
    provenance,
    quote_verification,
    interchange,
    interop_pandoc,
    supervision,
    locales,
    guide,
    research,
    integrity,
    api_keys,
    deposits,
    manuscripts,
    resolutions,
    active_registry,
    citation_schema,
    domain_profiles,
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
    submission_pack,
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


async def _ensure_default_institution() -> None:
    """First-run bootstrap (FRICTION_LOG F1): signup requires an institution
    matching DEFAULT_INSTITUTION_SHORT_NAME; a fresh deployment has none, so
    the very first user's signup used to fail. Idempotent."""
    from app.db.session import AsyncSessionLocal
    from app.models.institution import Institution

    settings = get_settings()
    short = settings.DEFAULT_INSTITUTION_SHORT_NAME.strip()
    if not short:
        return
    async with AsyncSessionLocal() as db:
        existing = (
            await db.execute(
                select(Institution).where(Institution.short_name == short)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return
        db.add(
            Institution(
                name=short,
                short_name=short,
                email_domains="",
                address="",
                short_address="",
                university_name=short,
                default_department="",
                department_aided=False,
            )
        )
        await db.commit()
        logging.getLogger(__name__).warning(
            "Bootstrapped default institution %r (edit its details in admin)", short
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
        await _ensure_default_institution()
    except Exception:
        log.exception("Default-institution bootstrap failed (continuing)")
    try:
        await _register_release()
    except Exception:
        log.exception("Release identity registration failed (continuing)")
    # Compliance: keep the daily retention sweep enqueued (idempotent per day;
    # executes on the queue worker). See app/services/retention_scheduler.py.
    import asyncio as _asyncio

    from app.services.retention_scheduler import retention_scheduler_loop

    sweep_task = _asyncio.create_task(retention_scheduler_loop())
    yield
    sweep_task.cancel()
    try:
        await sweep_task
    except (Exception, _asyncio.CancelledError):
        pass
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
    # Rate limiting: expose the limiter on app state and translate limit breaches
    # into 429s. Individual routes opt in with @limiter.limit(...).
    from slowapi import _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded

    from app.core.security_headers import SecurityHeadersMiddleware

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SecurityHeadersMiddleware)
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
        # Versioned mount. New clients target /v1; the router's own prefix is
        # preserved (e.g. /v1/auth, /v1/projects).
        app.include_router(module.router, prefix="/v1")
        # Legacy unversioned mount for the current frontend, on until it migrates.
        if settings.SERVE_UNVERSIONED_ROUTES:
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

    # Phase B SPA (docs/FRONTEND_LLD.md §19). Served at /app; the catch-all
    # returns the shell so client-side routes (e.g. /app/projects/{id}/library)
    # resolve. Its assets live under /static/spa/ (StaticFiles mount above).
    @app.get("/app", include_in_schema=False)
    async def frontend_spa() -> Response:
        return _serve_frontend(static_dir / "spa" / "index.html", "spa")

    @app.get("/app/{spa_path:path}", include_in_schema=False)
    async def frontend_spa_routes(spa_path: str) -> Response:
        return _serve_frontend(static_dir / "spa" / "index.html", "spa")

    register_exception_handlers(app)
    return app


app = create_app()
