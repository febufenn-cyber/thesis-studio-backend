"""FastAPI application entry point.

Wires together routers, configures CORS, sets up logging.

Run with:
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response

from app.api import auth as auth_router
from app.api import chat as chat_router
from app.api import compile as compile_router
from app.api import projects as projects_router
from app.api import sessions as sessions_router
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers


def _configure_logging() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=settings.LOG_LEVEL,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


async def _sweep_orphaned_compiles() -> None:
    """Mark files stuck in 'compiling' as failed after a process restart."""
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
            log.warning("Startup sweep: marked %d orphaned compile(s) failed", result.rowcount)


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
        log.exception("Startup sweep of orphaned compiles failed (continuing)")

    yield

    log.info("Robofox Thesis Studio API shutting down")


def _serve_frontend(path: Path, label: str) -> Response:
    """Serve a frontend file, returning a useful 404 if it is missing."""
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
        description="Backend for the AI-guided MA thesis writing platform.",
        version="0.2.0",
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

    app.include_router(auth_router.router)
    app.include_router(sessions_router.router)
    app.include_router(chat_router.router)
    app.include_router(compile_router.router)
    app.include_router(projects_router.router)

    @app.get("/healthz", tags=["meta"])
    async def health() -> dict:
        """Liveness probe."""
        return {"status": "ok", "frontend": "v2"}

    @app.get("/", include_in_schema=False)
    async def frontend_v2() -> Response:
        """Serve the v2 Formatting Studio as the default application."""
        return _serve_frontend(v2_index, "v2")

    @app.get("/legacy", include_in_schema=False)
    async def frontend_legacy() -> Response:
        """Preserve the original thesis-coaching UI for rollback and access."""
        return _serve_frontend(legacy_index, "legacy")

    register_exception_handlers(app)
    return app


app = create_app()
