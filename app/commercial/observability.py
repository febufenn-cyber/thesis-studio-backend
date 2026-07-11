"""Privacy-safe journey tracing and release identity.

Logs contain route templates, hashes and operational identifiers only. Request bodies,
query strings, emails, thesis text, quotations and AI prompts are never logged here.
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from uuid import uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import get_settings


log = logging.getLogger("robofox.journeys")
request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)
trace_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("trace_id", default=None)


def current_request_id() -> str | None:
    return request_id_var.get()


def current_trace_id() -> str | None:
    return trace_id_var.get()


def opaque_identifier(value: str | None) -> str | None:
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def release_identity() -> dict:
    settings = get_settings()
    return {
        "release_sha": settings.RELEASE_SHA or "development",
        "build_time": settings.BUILD_TIME or None,
        "schema_version": settings.SCHEMA_VERSION,
        "renderer_version": settings.RENDERER_VERSION,
        "prompt_bundle_version": settings.PROMPT_BUNDLE_VERSION,
        "canonical_schema_version": settings.CANONICAL_SCHEMA_VERSION,
        "environment": settings.ENV,
    }


class JourneyTracingMiddleware:
    """Attach request/trace IDs and emit one metadata-only completion record."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {key.decode().lower(): value.decode(errors="ignore") for key, value in scope.get("headers", [])}
        candidate = headers.get("x-request-id", "")
        request_id = candidate[:100] if candidate and all(ch.isalnum() or ch in "-_." for ch in candidate) else uuid4().hex
        trace_candidate = headers.get("x-trace-id", "")
        trace_id = trace_candidate[:100] if trace_candidate and all(ch.isalnum() or ch in "-_." for ch in trace_candidate) else request_id
        request_token = request_id_var.set(request_id)
        trace_token = trace_id_var.set(trace_id)
        started = time.perf_counter()
        status_code = 500
        response_bytes = 0

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code, response_bytes
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                response_headers = list(message.get("headers", []))
                response_headers.extend(
                    [
                        (b"x-request-id", request_id.encode()),
                        (b"x-trace-id", trace_id.encode()),
                        (b"x-release-sha", (get_settings().RELEASE_SHA or "development").encode()),
                    ]
                )
                message["headers"] = response_headers
            elif message["type"] == "http.response.body":
                response_bytes += len(message.get("body", b""))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            path = str(scope.get("path") or "")
            route = scope.get("route")
            route_template = getattr(route, "path", None) or path
            client = scope.get("client")
            record = {
                "at": datetime.now(timezone.utc).isoformat(),
                "event": "http_request_completed",
                "request_id": request_id,
                "trace_id": trace_id,
                "method": scope.get("method"),
                "route": route_template,
                "status": status_code,
                "duration_ms": duration_ms,
                "response_bytes": response_bytes,
                "client_hash": opaque_identifier(str(client[0]) if client else None),
                "release_sha": get_settings().RELEASE_SHA or "development",
            }
            log.info(json.dumps(record, separators=(",", ":"), sort_keys=True))
            request_id_var.reset(request_token)
            trace_id_var.reset(trace_token)
