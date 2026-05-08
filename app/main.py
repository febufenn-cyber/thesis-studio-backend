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
from fastapi.responses import FileResponse

from app.api import auth as auth_router
from app.api import chat as chat_router
from app.api import sessions as sessions_router
from app.core.config import get_settings


# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------

def _configure_logging() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=settings.LOG_LEVEL,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


# ---------------------------------------------------------------------------
# Lifespan: startup / shutdown hooks
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    _configure_logging()
    log = logging.getLogger(__name__)

    settings = get_settings()
    log.info("Robofox Thesis Studio API starting up")
    log.info("Environment: %s, debug=%s", settings.ENV, settings.DEBUG)

    yield

    log.info("Robofox Thesis Studio API shutting down")


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app() -> FastAPI:
    settings = get_settings()
    static_index = Path(__file__).parent / "static" / "index.html"

    app = FastAPI(
        title="Robofox Thesis Studio API",
        description="Backend for the AI-guided MA thesis writing platform.",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.DEBUG else None,
        redoc_url=None,
    )

    # CORS — frontend origins from settings.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,  # required for cookies
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    # Routers
    app.include_router(auth_router.router)
    app.include_router(sessions_router.router)
    app.include_router(chat_router.router)  # registers POST /sessions/{id}/messages

    @app.get("/healthz", tags=["meta"])
    async def health() -> dict:
        """Liveness probe."""
        return {"status": "ok"}

    @app.get("/", include_in_schema=False)
    async def frontend() -> FileResponse:
        """Serve the embedded frontend app."""
        return FileResponse(static_index)

    return app


app = create_app()
