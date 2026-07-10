"""Centralised exception handlers for the FastAPI application.

Register all handlers via ``register_exception_handlers(app)`` inside
``create_app()`` in app/main.py.  Each handler maps a specific exception
class to an HTTP status code and a user-safe detail string.

Logging policy: every handler calls ``log.exception(...)`` so the full
traceback is captured, but NO request body, query params, or headers are
ever included in the log output.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.services.claude_service import ClaudeRateLimitError, ClaudeSubprocessError


log = logging.getLogger(__name__)


async def _handle_rate_limit(request: Request, exc: ClaudeRateLimitError) -> JSONResponse:
    """Return 429 when the Claude Max session limit is reached."""
    log.exception("Claude rate-limit error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=429,
        content={"detail": "The AI service is rate-limited right now. Please try again in a few minutes."},
    )


async def _handle_subprocess_error(request: Request, exc: ClaudeSubprocessError) -> JSONResponse:
    """Return 503 when the Claude subprocess fails."""
    log.exception("Claude subprocess error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=503,
        content={"detail": "The AI service is temporarily unavailable."},
    )


async def _handle_integrity_error(request: Request, exc: IntegrityError) -> JSONResponse:
    """Return 409 on database uniqueness / FK constraint violations."""
    log.exception("Database integrity error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=409,
        content={"detail": "Conflict with existing data."},
    )


async def _handle_sqlalchemy_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    """Return 500 for any other SQLAlchemy-level database error."""
    log.exception("Database error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal database error."},
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Attach all exception handlers to *app*.

    Call this inside ``create_app()`` before returning the application
    instance so that handlers are active for every request.
    """
    app.add_exception_handler(ClaudeRateLimitError, _handle_rate_limit)
    app.add_exception_handler(ClaudeSubprocessError, _handle_subprocess_error)
    # IntegrityError must be registered before SQLAlchemyError; Starlette
    # resolves by MRO so this ordering is informational only, but explicit.
    app.add_exception_handler(IntegrityError, _handle_integrity_error)
    app.add_exception_handler(SQLAlchemyError, _handle_sqlalchemy_error)
