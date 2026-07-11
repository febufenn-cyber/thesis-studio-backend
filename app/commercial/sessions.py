"""Revocable server-side application sessions and sensitive-action checks."""

from __future__ import annotations

import hashlib
import ipaddress
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import create_access_token
from app.models.commercial import ApplicationSession
from app.models.event import Event
from app.models.user import User


class SessionInvalid(RuntimeError):
    pass


class ReauthenticationRequired(RuntimeError):
    pass


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _privacy_hash(value: str) -> str:
    settings = get_settings()
    return hashlib.sha256(
        (settings.effective_privacy_hash_pepper + "\x00" + value).encode("utf-8")
    ).hexdigest()


def _ip_prefix(host: str | None) -> str | None:
    if not host:
        return None
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return None
    if address.version == 4:
        network = ipaddress.ip_network(f"{address}/24", strict=False)
    else:
        network = ipaddress.ip_network(f"{address}/56", strict=False)
    return str(network.network_address) + f"/{network.prefixlen}"


def request_fingerprint(request: Request | None) -> tuple[str | None, str | None, str | None]:
    if request is None:
        return None, None, None
    user_agent = request.headers.get("user-agent", "")[:2000]
    host = request.client.host if request.client else None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        host = forwarded.split(",", 1)[0].strip()
    prefix = _ip_prefix(host)
    device = request.headers.get("x-device-name") or None
    return (
        device[:200] if device else None,
        _privacy_hash(user_agent) if user_agent else None,
        _privacy_hash(prefix) if prefix else None,
    )


async def issue_session(
    db: AsyncSession,
    user: User,
    *,
    auth_method: str,
    request: Request | None = None,
) -> tuple[ApplicationSession, str]:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    device_label, user_agent_hash, ip_prefix_hash = request_fingerprint(request)
    row = ApplicationSession(
        user_id=user.id,
        token_hash=hashlib.sha256(secrets.token_bytes(32)).hexdigest(),
        device_label=device_label,
        user_agent_hash=user_agent_hash,
        ip_prefix_hash=ip_prefix_hash,
        auth_method=auth_method,
        idle_expires_at=now + timedelta(minutes=settings.SESSION_IDLE_MINUTES),
        absolute_expires_at=now + timedelta(days=settings.SESSION_ABSOLUTE_DAYS),
        reauthenticated_at=now,
    )
    db.add(row)
    await db.flush()
    token = create_access_token(user.id, session_id=row.id)
    row.token_hash = token_hash(token)
    db.add(
        Event(
            project_id=None,
            user_id=user.id,
            kind="application_session_created",
            data={
                "session_id": str(row.id),
                "auth_method": auth_method,
                "device_label": row.device_label,
            },
        )
    )
    await db.flush()
    return row, token


async def validate_session(
    db: AsyncSession,
    *,
    user_id: UUID,
    session_id: UUID,
    token: str,
    touch: bool = True,
) -> ApplicationSession:
    now = datetime.now(timezone.utc)
    row = (
        await db.execute(
            select(ApplicationSession).where(
                ApplicationSession.id == session_id,
                ApplicationSession.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if row is None or row.state != "active":
        raise SessionInvalid("Session has been revoked or does not exist.")
    if row.absolute_expires_at <= now or row.idle_expires_at <= now:
        row.state = "expired"
        row.revoked_at = now
        row.revoke_reason = "Session lifetime expired."
        await db.commit()
        raise SessionInvalid("Session expired.")
    if not secrets.compare_digest(row.token_hash, token_hash(token)):
        raise SessionInvalid("Session token does not match the active device session.")
    if touch and (now - row.last_seen_at) >= timedelta(minutes=5):
        row.last_seen_at = now
        idle_target = now + timedelta(minutes=get_settings().SESSION_IDLE_MINUTES)
        row.idle_expires_at = min(idle_target, row.absolute_expires_at)
        await db.commit()
    return row


async def revoke_session(
    db: AsyncSession,
    row: ApplicationSession,
    *,
    actor_id: UUID,
    reason: str,
) -> ApplicationSession:
    if row.state == "active":
        row.state = "revoked"
        row.revoked_at = datetime.now(timezone.utc)
        row.revoked_by = actor_id
        row.revoke_reason = reason[:2000]
        db.add(
            Event(
                project_id=None,
                user_id=actor_id,
                kind="application_session_revoked",
                data={
                    "session_id": str(row.id),
                    "session_user_id": str(row.user_id),
                    "reason": reason[:500],
                },
            )
        )
    await db.flush()
    return row


async def revoke_all_sessions(
    db: AsyncSession,
    user_id: UUID,
    *,
    actor_id: UUID,
    reason: str,
    except_session_id: UUID | None = None,
) -> int:
    rows = list(
        (
            await db.execute(
                select(ApplicationSession).where(
                    ApplicationSession.user_id == user_id,
                    ApplicationSession.state == "active",
                )
            )
        ).scalars()
    )
    count = 0
    for row in rows:
        if except_session_id is not None and row.id == except_session_id:
            continue
        await revoke_session(db, row, actor_id=actor_id, reason=reason)
        count += 1
    return count


async def require_recent_reauthentication(
    session: ApplicationSession,
    *,
    minutes: int | None = None,
) -> None:
    window = minutes if minutes is not None else get_settings().SESSION_REAUTH_MINUTES
    if session.reauthenticated_at < datetime.now(timezone.utc) - timedelta(minutes=window):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Reauthentication is required for this sensitive action.",
            headers={"X-Reauthentication-Required": "true"},
        )


async def mark_reauthenticated(db: AsyncSession, row: ApplicationSession, actor_id: UUID) -> None:
    row.reauthenticated_at = datetime.now(timezone.utc)
    db.add(
        Event(
            project_id=None,
            user_id=actor_id,
            kind="application_session_reauthenticated",
            data={"session_id": str(row.id)},
        )
    )
    await db.flush()
