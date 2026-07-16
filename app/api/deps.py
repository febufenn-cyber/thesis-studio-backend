"""FastAPI dependencies — revocable authentication and access control."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.commercial.sessions import SessionInvalid, validate_session
from app.core.config import get_settings
from app.core.security import decode_access_token_claims
from app.db.deps import get_db
from app.models.api_key import ApiKey
from app.models.commercial import ApplicationSession
from app.models.project import Project
from app.models.session import ThesisSession
from app.models.user import User

API_KEY_PREFIX = "ak_"


def hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


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


# --- API-key scope enforcement (fail-closed) --------------------------------
#
# An API key may do ONLY what one of its scopes explicitly grants; everything
# else — project mutations, collaboration, billing, auth, and API-key
# management itself — is session-only. A key can never mint, list or revoke
# keys. PUT/PATCH/DELETE are never key-accessible.
#
#   read     any GET
#   export   GET/POST on export, interchange, bibliography and pandoc surfaces
#   resolve  POST on reference resolution/search and advisory verification
#   import   POST on reference import (BibTeX/RIS/CSL, Zotero)

_KEY_DENIED_PREFIXES = ("/api-keys", "/auth")

_EXPORT_GET_MARKERS = ("/export/", "/exports", "/bibliography/styles", "/interop/formats")
_EXPORT_POST_MARKERS = ("/export/pandoc", "/bibliography/render", "/interop/convert")
_RESOLVE_POST_MARKERS = (
    "/references/resolve",
    "/references/search",
    "/verify-auto",
    "/verify-source",
)
_IMPORT_POST_MARKERS = ("/references/import", "/references/zotero/import")


def api_key_permits(scopes: list[str] | None, method: str, path: str) -> bool:
    """True when a key with ``scopes`` may perform ``method path``. Default deny."""
    p = path[3:] if path.startswith("/v1/") else path
    if any(p == d or p.startswith(d + "/") or p.startswith(d + "?") for d in _KEY_DENIED_PREFIXES):
        return False
    granted = set(scopes or [])
    if method == "GET":
        if "read" in granted:
            return True
        return "export" in granted and any(m in p for m in _EXPORT_GET_MARKERS)
    if method == "POST":
        if "resolve" in granted and any(m in p for m in _RESOLVE_POST_MARKERS):
            return True
        if "import" in granted and any(m in p for m in _IMPORT_POST_MARKERS):
            return True
        if "export" in granted and any(m in p for m in _EXPORT_POST_MARKERS):
            return True
        return False
    return False


async def _api_key_user(db: AsyncSession, raw_key: str, *, method: str, path: str) -> User:
    """Resolve a user from a bearer API key; enforce the key's scopes."""
    row = (
        await db.execute(
            select(ApiKey).where(
                ApiKey.key_hash == hash_api_key(raw_key),
                ApiKey.revoked_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise _UNAUTH
    if not api_key_permits(row.scopes, method.upper(), path):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This API key's scopes do not permit that operation.",
        )
    row.last_used_at = datetime.now(timezone.utc)
    user = (
        await db.execute(select(User).where(User.id == row.user_id))
    ).scalar_one_or_none()
    if user is None or getattr(user, "account_status", "active") != "active":
        raise _UNAUTH
    return user


async def get_current_user(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    access_token: Annotated[str | None, Cookie()] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    """Resolve a user via cookie/JWT or a bearer API key (scope-enforced)."""
    # Bearer API keys (ak_...) are a distinct auth path; try them before JWT.
    if authorization and authorization.lower().startswith("bearer "):
        candidate = authorization[7:].strip()
        if candidate.startswith(API_KEY_PREFIX):
            return await _api_key_user(
                db, candidate, method=request.method, path=request.url.path
            )

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
