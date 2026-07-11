"""Device-visible session management and sensitive-action reauthentication."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentApplicationSession, CurrentUser
from app.collaboration.capabilities import require_institution_capability
from app.commercial.sessions import (
    mark_reauthenticated,
    require_recent_reauthentication,
    revoke_all_sessions,
    revoke_session,
)
from app.core.config import get_settings
from app.core.security import hash_magic_link_token
from app.db.deps import get_db
from app.models.auth_token import AuthToken
from app.models.commercial import ApplicationSession
from app.models.user import User


router = APIRouter(tags=["commercial-sessions"])


class ReauthenticateRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")


class RevokeAllRequest(BaseModel):
    keep_current: bool = True
    reason: str = Field("User requested session revocation.", min_length=3, max_length=1000)


class AdminRevokeRequest(BaseModel):
    reason: str = Field(..., min_length=5, max_length=2000)


def _session_dict(row: ApplicationSession, current_id: UUID) -> dict:
    return {
        "id": row.id,
        "current": row.id == current_id,
        "device_label": row.device_label or "Unknown device",
        "auth_method": row.auth_method,
        "state": row.state,
        "created_at": row.created_at,
        "last_seen_at": row.last_seen_at,
        "idle_expires_at": row.idle_expires_at,
        "absolute_expires_at": row.absolute_expires_at,
        "reauthenticated_at": row.reauthenticated_at,
        "revoked_at": row.revoked_at,
        "revoke_reason": row.revoke_reason,
    }


@router.get("/auth/sessions")
async def list_sessions(
    current_user: CurrentUser,
    current_session: CurrentApplicationSession,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    rows = list(
        (
            await db.execute(
                select(ApplicationSession)
                .where(ApplicationSession.user_id == current_user.id)
                .order_by(ApplicationSession.last_seen_at.desc())
            )
        ).scalars()
    )
    return [_session_dict(row, current_session.id) for row in rows]


@router.delete("/auth/sessions/{session_id}")
async def revoke_device_session(
    session_id: UUID,
    response: Response,
    current_user: CurrentUser,
    current_session: CurrentApplicationSession,
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = (
        await db.execute(
            select(ApplicationSession).where(
                ApplicationSession.id == session_id,
                ApplicationSession.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    await revoke_session(db, row, actor_id=current_user.id, reason="User revoked this device session.")
    await db.commit()
    if row.id == current_session.id:
        response.delete_cookie(get_settings().SESSION_COOKIE_NAME)
    return {"id": row.id, "state": row.state, "revoked_at": row.revoked_at}


@router.post("/auth/sessions/revoke-all")
async def revoke_every_session(
    body: RevokeAllRequest,
    response: Response,
    current_user: CurrentUser,
    current_session: CurrentApplicationSession,
    db: AsyncSession = Depends(get_db),
) -> dict:
    count = await revoke_all_sessions(
        db,
        current_user.id,
        actor_id=current_user.id,
        reason=body.reason,
        except_session_id=current_session.id if body.keep_current else None,
    )
    await db.commit()
    if not body.keep_current:
        response.delete_cookie(get_settings().SESSION_COOKIE_NAME)
    return {"revoked": count, "current_session_preserved": body.keep_current}


@router.post("/auth/sessions/reauthenticate")
async def reauthenticate_session(
    body: ReauthenticateRequest,
    current_user: CurrentUser,
    current_session: CurrentApplicationSession,
    db: AsyncSession = Depends(get_db),
) -> dict:
    now = datetime.now(timezone.utc)
    token = (
        await db.execute(
            select(AuthToken)
            .where(AuthToken.user_id == current_user.id)
            .where(AuthToken.kind == "otp")
            .where(AuthToken.used_at.is_(None))
            .where(AuthToken.expires_at > now)
            .order_by(AuthToken.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if token is None or token.attempts >= 5:
        raise HTTPException(status_code=401, detail="Invalid or expired code")
    expected = hash_magic_link_token(f"otp:{current_user.id}:{body.code}")
    if token.token_hash != expected:
        token.attempts += 1
        await db.commit()
        raise HTTPException(status_code=401, detail="Invalid or expired code")
    token.used_at = now
    await mark_reauthenticated(db, current_session, current_user.id)
    await db.commit()
    return {"ok": True, "session_id": current_session.id, "reauthenticated_at": current_session.reauthenticated_at}


@router.post("/institutions/{institution_id}/members/{user_id}/revoke-sessions")
async def administrator_revoke_member_sessions(
    institution_id: UUID,
    user_id: UUID,
    body: AdminRevokeRequest,
    current_user: CurrentUser,
    current_session: CurrentApplicationSession,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_institution_capability(db, institution_id, current_user, "session.revoke_member")
    await require_recent_reauthentication(current_session)
    target = (
        await db.execute(select(User).where(User.id == user_id, User.institution_id == institution_id))
    ).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="Institution member not found")
    count = await revoke_all_sessions(
        db,
        user_id,
        actor_id=current_user.id,
        reason=body.reason,
    )
    await db.commit()
    return {"user_id": user_id, "revoked": count}
