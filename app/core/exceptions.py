"""Centralised exception handlers for the FastAPI application.

Register all handlers via ``register_exception_handlers(app)`` inside
``create_app()`` in app/main.py. Each handler maps a specific exception
class to an HTTP status code and a user-safe detail string.

Logging policy: handlers record the route and exception class, but never request
bodies, query parameters, upload names, manuscript content or authentication data.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.services.claude_service import ClaudeRateLimitError, ClaudeSubprocessError
from app.services.malware_service import MalwareDetectedError, MalwareScannerUnavailableError


log = logging.getLogger(__name__)


async def _handle_rate_limit(request: Request, exc: ClaudeRateLimitError) -> JSONResponse:
    log.exception("Claude rate-limit error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=429,
        content={"detail": "The AI service is rate-limited right now. Please try again later."},
    )


async def _handle_subprocess_error(request: Request, exc: ClaudeSubprocessError) -> JSONResponse:
    log.exception("Claude subprocess error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=503,
        content={"detail": "The AI service is temporarily unavailable."},
    )


async def _handle_malware_detected(request: Request, exc: MalwareDetectedError) -> JSONResponse:
    log.warning("Malware-positive upload rejected on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=422,
        content={"detail": "The uploaded document failed the malware safety check."},
    )


async def _handle_malware_unavailable(
    request: Request, exc: MalwareScannerUnavailableError
) -> JSONResponse:
    log.exception("Malware scanner unavailable on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=503,
        content={
            "detail": "Document uploads are temporarily unavailable because the safety scanner did not respond."
        },
    )


async def _handle_integrity_error(request: Request, exc: IntegrityError) -> JSONResponse:
    log.exception("Database integrity error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=409,
        content={"detail": "Conflict with existing data."},
    )


async def _handle_sqlalchemy_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    log.exception("Database error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal database error."},
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Attach user-safe handlers to the application."""

    app.add_exception_handler(ClaudeRateLimitError, _handle_rate_limit)
    app.add_exception_handler(ClaudeSubprocessError, _handle_subprocess_error)
    app.add_exception_handler(MalwareDetectedError, _handle_malware_detected)
    app.add_exception_handler(MalwareScannerUnavailableError, _handle_malware_unavailable)
    app.add_exception_handler(IntegrityError, _handle_integrity_error)
    app.add_exception_handler(SQLAlchemyError, _handle_sqlalchemy_error)
