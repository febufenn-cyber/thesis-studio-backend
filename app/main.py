"""FastAPI application entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app.api import active_registry as active_registry_router
from app.api import auth as auth_router
from app.api import chat as chat_router
from app.api import compile as compile_router
from app.api import editor as editor_router
from app.api import manuscripts as manuscripts_router
from app.api import previews as previews_router
from app.api import projects as projects_router
from app.api import resolutions as resolutions_router
from app.api import review_workspace as review_workspace_router
from app.api import sessions as sessions_router
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
    from sqlalchemy import update

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    _configure_logging()
    log = logging.getLogger(__name__)
    settings = get_settings()
    log.info("Robofox Thesis Studio API starting up")
    log.info("Environment: %s, debug=%s", settings.ENV, settings.DEBUG)
    try:
        await _sweep_orphaned_compiles()
    except Exception:
        log.exception("Startup sweep of legacy compiles failed (continuing)")
    yield
    log.info("Robofox Thesis Studio API shutting down")


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
        description="Integrity-first academic manuscript conversion, human review and thesis workflow.",
        version="0.4.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.DEBUG else None,
        redoc_url=None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    app.include_router(auth_router.router)
    app.include_router(sessions_router.router)
    app.include_router(chat_router.router)
    app.include_router(compile_router.router)
    app.include_router(projects_router.router)
    app.include_router(manuscripts_router.router)
    app.include_router(resolutions_router.router)
    app.include_router(active_registry_router.router)
    app.include_router(editor_router.router)
    app.include_router(review_workspace_router.router)
    app.include_router(previews_router.router)

    @app.get("/healthz", tags=["meta"])
    async def health() -> dict:
        return {"status": "ok", "frontend": "v2", "phase": "human_review_workspace"}

    @app.get("/readyz", tags=["meta"])
    async def ready():
        report = await readiness_report()
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
