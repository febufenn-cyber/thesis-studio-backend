"""ASGI-level commercial guards for product entry points.

This is authorization/capacity enforcement, not presentation logic. It protects both
current and future frontends without duplicating plan-name checks inside controllers.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from http.cookies import SimpleCookie
from uuid import UUID

from sqlalchemy import func, select
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.commercial.entitlements import (
    EntitlementContext,
    EntitlementDenied,
    EntitlementQuotaExceeded,
    record_usage,
    require_entitlement,
    resolve_entitlement,
)
from app.commercial.sessions import SessionInvalid, validate_session
from app.core.config import get_settings
from app.core.security import decode_access_token_claims
from app.db.session import AsyncSessionLocal
from app.models.project import Project
from app.models.user import User


_PROJECT_PATH = re.compile(r"^/projects/([0-9a-fA-F-]{36})/(manuscript|exports|review-cycles)$")


class CommercialGuardMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    @staticmethod
    def _headers(scope: Scope) -> dict[str, str]:
        return {
            key.decode("latin1").lower(): value.decode("latin1")
            for key, value in scope.get("headers", [])
        }

    @staticmethod
    def _token(headers: dict[str, str]) -> str | None:
        authorization = headers.get("authorization", "")
        if authorization.lower().startswith("bearer "):
            return authorization[7:].strip()
        cookie_header = headers.get("cookie", "")
        if not cookie_header:
            return None
        cookies = SimpleCookie()
        try:
            cookies.load(cookie_header)
        except Exception:
            return None
        morsel = cookies.get(get_settings().SESSION_COOKIE_NAME)
        return morsel.value if morsel else None

    @staticmethod
    async def _json_response(send: Send, status: int, detail: str, headers: list[tuple[bytes, bytes]] | None = None) -> None:
        body = json.dumps({"detail": detail}, separators=(",", ":")).encode("utf-8")
        response_headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode("ascii")),
        ]
        response_headers.extend(headers or [])
        await send({"type": "http.response.start", "status": status, "headers": response_headers})
        await send({"type": "http.response.body", "body": body})

    async def _identity(self, headers: dict[str, str]) -> tuple[User | None, str | None]:
        token = self._token(headers)
        if not token:
            return None, None
        try:
            claims = decode_access_token_claims(token)
        except Exception:
            return None, token
        async with AsyncSessionLocal() as db:
            if claims.session_id is not None:
                try:
                    await validate_session(
                        db,
                        user_id=claims.user_id,
                        session_id=claims.session_id,
                        token=token,
                        touch=False,
                    )
                except SessionInvalid:
                    return None, token
            user = (
                await db.execute(select(User).where(User.id == claims.user_id))
            ).scalar_one_or_none()
            return user, token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") != "POST":
            await self.app(scope, receive, send)
            return
        path = str(scope.get("path") or "")
        project_match = _PROJECT_PATH.match(path)
        guarded = path == "/projects" or project_match is not None
        if not guarded:
            await self.app(scope, receive, send)
            return

        headers = self._headers(scope)
        user, _ = await self._identity(headers)
        if user is None:
            # Authentication dependency remains the source of the user-facing 401.
            await self.app(scope, receive, send)
            return

        buffered_body = b""
        body_payload: dict = {}
        if project_match and project_match.group(2) == "exports":
            more = True
            messages: list[Message] = []
            while more:
                message = await receive()
                messages.append(message)
                if message["type"] == "http.request":
                    buffered_body += message.get("body", b"")
                    more = bool(message.get("more_body", False))
                else:
                    more = False
            try:
                body_payload = json.loads(buffered_body or b"{}")
            except json.JSONDecodeError:
                body_payload = {}
            delivered = False

            async def receive_replay() -> Message:
                nonlocal delivered
                if delivered:
                    return {"type": "http.request", "body": b"", "more_body": False}
                delivered = True
                return {"type": "http.request", "body": buffered_body, "more_body": False}

            downstream_receive = receive_replay
        else:
            downstream_receive = receive

        institution_id = user.institution_id
        project_id: UUID | None = None
        context = EntitlementContext(institution_id=institution_id, user_id=user.id)
        successful_usage: list[tuple[str, str, Decimal, str, str]] = []
        try:
            async with AsyncSessionLocal() as db:
                if path == "/projects":
                    await require_entitlement(db, context, "project.create")
                    limit = await resolve_entitlement(db, context, "project.active_limit")
                    active_count = int(
                        (
                            await db.execute(
                                select(func.count(Project.id)).where(
                                    Project.user_id == user.id,
                                    Project.archived.is_(False),
                                )
                            )
                        ).scalar_one()
                    )
                    if isinstance(limit.value, (int, float, Decimal)) and active_count >= int(limit.value):
                        raise EntitlementQuotaExceeded(
                            f"Active project limit reached ({int(limit.value)}). Archive a project or upgrade the contract."
                        )
                    successful_usage.append(("project.create", "create_project", Decimal(1), "project", "month"))
                else:
                    project_id = UUID(project_match.group(1))
                    project = (
                        await db.execute(
                            select(Project).where(
                                Project.id == project_id,
                                Project.user_id == user.id,
                                Project.archived.is_(False),
                            )
                        )
                    ).scalar_one_or_none()
                    if project is None:
                        await self.app(scope, downstream_receive, send)
                        return
                    institution_id = project.institution_id or institution_id
                    context = EntitlementContext(
                        institution_id=institution_id,
                        user_id=user.id,
                        project_id=project.id,
                    )
                    action = project_match.group(2)
                    if action == "manuscript":
                        decision = await resolve_entitlement(db, context, "manuscript.max_size_mb")
                        content_length = int(headers.get("content-length") or 0)
                        if isinstance(decision.value, (int, float, Decimal)):
                            max_bytes = int(decision.value) * 1024 * 1024
                            if content_length and content_length > max_bytes:
                                raise EntitlementQuotaExceeded(
                                    f"Manuscript upload exceeds the {int(decision.value)} MB allowance."
                                )
                        successful_usage.append(("manuscript.ingestion", "upload_manuscript", Decimal(content_length), "bytes", "month"))
                    elif action == "review-cycles":
                        await require_entitlement(db, context, "review.supervisor")
                    elif action == "exports":
                        requested = body_payload.get("formats", [])
                        formats = {"docx", "pdf", "md", "txt"} if requested == "all" else set(requested or [])
                        if "docx" in formats:
                            await require_entitlement(db, context, "export.docx")
                        if "pdf" in formats:
                            await require_entitlement(
                                db,
                                context,
                                "export.pdf",
                            )
                            await require_entitlement(
                                db,
                                context,
                                "export.pdf.monthly",
                                reset_period="month",
                            )
                            successful_usage.append(("export.pdf.monthly", "generate_pdf", Decimal(1), "pdf_export", "month"))
        except EntitlementDenied as exc:
            await self._json_response(send, 403, str(exc))
            return
        except EntitlementQuotaExceeded as exc:
            await self._json_response(send, 429, str(exc), [(b"retry-after", b"3600")])
            return

        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
            await send(message)

        await self.app(scope, downstream_receive, send_wrapper)
        if 200 <= status_code < 300 and successful_usage:
            async with AsyncSessionLocal() as db:
                for key, operation, quantity, unit, reset_period in successful_usage:
                    await record_usage(
                        db,
                        context,
                        key,
                        operation,
                        quantity=quantity,
                        unit=unit,
                        reset_period=reset_period,
                        idempotency_key=(
                            f"http:{scope.get('method')}:{path}:{project_id or user.id}:"
                            f"{headers.get('x-idempotency-key') or headers.get('x-request-id') or ''}:"
                            f"{key}"
                        ) if (headers.get("x-idempotency-key") or headers.get("x-request-id")) else None,
                    )
                await db.commit()
