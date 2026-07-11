"""FastAPI dependencies — revocable authentication and access control."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.commercial.sessions import SessionInvalid, validate_session
from app.core.config import get_settings
from app.core.security import decode_access_token_claims
from app.db.deps import get_db
from app.models.commercial import ApplicationSession
from app.models.project import Project
from app.models.session import ThesisSession
from app.models.user import User


_UNAUTH = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


def _extract_token(cookie: str | None, auth_header: str | None) -> str | None:
    if cookie:
        return cookie
    if auth_header and auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return None


async def _claims_and_token(
    access_token: str | None,
    authorization: str | None,
):
    token = _extract_token(access_token, authorization)
    if not token:
        raise _UNAUTH
    try:
        claims = decode_access_token_claims(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired") from None
    except (jwt.InvalidTokenError, ValueError, KeyError):
        raise _UNAUTH from None
    return claims, token


async def get_current_user(
    db: Annotated[AsyncSession, Depends(get_db)],
    access_token: Annotated[str | None, Cookie()] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    """Resolve a user only while the signed token and server session are active."""
    claims, token = await _claims_and_token(access_token, authorization)
    if claims.session_id is not None:
        try:
            await validate_session(
                db,
                user_id=claims.user_id,
                session_id=claims.session_id,
                token=token,
            )
        except SessionInvalid as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from None
    elif get_settings().ENV == "production":
        # Pilot cookies without ``sid`` are tolerated outside production only so
        # existing development sessions can migrate without weakening paid access.
        raise HTTPException(status_code=401, detail="Sign in again to create a revocable session.")

    user = (
        await db.execute(select(User).where(User.id == claims.user_id))
    ).scalar_one_or_none()
    if user is None or getattr(user, "account_status", "active") != "active":
        raise _UNAUTH
    return user


async def get_current_application_session(
    db: Annotated[AsyncSession, Depends(get_db)],
    access_token: Annotated[str | None, Cookie()] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> ApplicationSession:
    claims, token = await _claims_and_token(access_token, authorization)
    if claims.session_id is None:
        raise HTTPException(status_code=401, detail="Sign in again to create a revocable session.")
    try:
        return await validate_session(
            db,
            user_id=claims.user_id,
            session_id=claims.session_id,
            token=token,
        )
    except SessionInvalid as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from None


CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentApplicationSession = Annotated[ApplicationSession, Depends(get_current_application_session)]


async def fetch_owned_session(
    db: AsyncSession,
    session_id: UUID,
    user_id: UUID,
) -> ThesisSession:
    result = await db.execute(
        select(ThesisSession)
        .where(ThesisSession.id == session_id)
        .where(ThesisSession.user_id == user_id)
        .where(ThesisSession.archived.is_(False))
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return row


async def fetch_owned_project(
    db: AsyncSession,
    project_id: UUID,
    user_id: UUID,
) -> Project:
    result = await db.execute(
        select(Project)
        .where(Project.id == project_id)
        .where(Project.user_id == user_id)
        .where(Project.archived.is_(False))
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return row
