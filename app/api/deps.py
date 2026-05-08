"""FastAPI dependencies — auth and access control.

Every endpoint that touches user-owned data must use `get_current_user`.
"""

from __future__ import annotations

from typing import Annotated

import jwt
from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.db.deps import get_db
from app.models.user import User


_UNAUTH = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(
    db: Annotated[AsyncSession, Depends(get_db)],
    access_token: Annotated[str | None, Cookie()] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    """Resolve the current user from JWT (cookie preferred, Authorization header fallback).

    Raises 401 if missing, expired, malformed, or no matching user.
    """
    token = _extract_token(access_token, authorization)
    if not token:
        raise _UNAUTH

    try:
        user_id = decode_access_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
        ) from None
    except (jwt.InvalidTokenError, ValueError, KeyError):
        raise _UNAUTH from None

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise _UNAUTH

    return user


def _extract_token(cookie: str | None, auth_header: str | None) -> str | None:
    """Prefer the cookie (set by the magic-link callback), fall back to Bearer header."""
    if cookie:
        return cookie
    if auth_header and auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return None


# Convenient alias for type-annotating route handlers.
CurrentUser = Annotated[User, Depends(get_current_user)]
