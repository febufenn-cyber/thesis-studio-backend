"""Authentication routes with opaque one-time credentials and revocable sessions."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.commercial.sessions import issue_session, revoke_session, validate_session
from app.core.config import get_settings
from app.core.rate_limit import limiter
from app.core.security import (
    decode_access_token_claims,
    generate_magic_link_token,
    hash_magic_link_token,
)
from app.db.deps import get_db
from app.models.auth_token import AuthToken
from app.models.commercial import ApplicationSession
from app.models.institution import Institution
from app.models.user import User
from app.schemas.auth import (
    AuthConfigResponse,
    CurrentUserResponse,
    GoogleAuthRequest,
    MagicLinkRequest,
    MagicLinkResponse,
    OtpRequest,
    OtpResponse,
    OtpVerifyRequest,
)
from app.services.email_service import send_magic_link_email, send_otp_email
from app.services.google_auth import GoogleAuthError, verify_google_credential


log = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/request-link", response_model=MagicLinkResponse)
@limiter.limit(get_settings().RATE_LIMIT_AUTH)
async def request_magic_link(
    request: Request,
    body: MagicLinkRequest,
    db: AsyncSession = Depends(get_db),
) -> MagicLinkResponse:
    settings = get_settings()
    email = body.email.lower().strip()
    user = await _get_or_create_user(db, email)
    if user is None:
        log.error(
            "Magic-link request failed: default institution '%s' not found",
            settings.DEFAULT_INSTITUTION_SHORT_NAME,
        )
        return MagicLinkResponse()

    now = datetime.now(timezone.utc)
    recent = await db.execute(
        select(AuthToken.id)
        .where(AuthToken.user_id == user.id)
        .where(AuthToken.used_at.is_(None))
        .where(AuthToken.expires_at > now)
        .where(AuthToken.created_at > now - timedelta(minutes=3))
        .limit(1)
    )
    if recent.scalar_one_or_none() is not None:
        log.info("Magic-link cooldown active for user %s", user.id)
        return MagicLinkResponse()

    raw_token, hashed_token = generate_magic_link_token()
    db.add(
        AuthToken(
            user_id=user.id,
            token_hash=hashed_token,
            expires_at=now + timedelta(minutes=settings.MAGIC_LINK_EXPIRY_MINUTES),
        )
    )
    await db.commit()
    link_url = settings.magic_link_url_template.format(token=raw_token)
    try:
        await send_magic_link_email(to_email=email, link_url=link_url)
    except Exception:
        log.exception("Failed to send magic-link email")
    return MagicLinkResponse(magic_link=link_url) if settings.DEBUG else MagicLinkResponse()


@router.post("/request-otp", response_model=OtpResponse)
@limiter.limit(get_settings().RATE_LIMIT_AUTH)
async def request_otp(
    request: Request,
    body: OtpRequest,
    db: AsyncSession = Depends(get_db),
) -> OtpResponse:
    import secrets

    settings = get_settings()
    email = body.email.lower().strip()
    user = await _get_or_create_user(db, email)
    if user is None:
        log.error("OTP request failed: default institution missing")
        return OtpResponse()

    now = datetime.now(timezone.utc)
    recent = await db.execute(
        select(AuthToken.id)
        .where(AuthToken.user_id == user.id)
        .where(AuthToken.kind == "otp")
        .where(AuthToken.used_at.is_(None))
        .where(AuthToken.expires_at > now)
        .where(AuthToken.created_at > now - timedelta(seconds=60))
        .limit(1)
    )
    if recent.scalar_one_or_none() is not None:
        log.info("OTP cooldown active for %s", _redact(email))
        return OtpResponse()

    code = f"{secrets.randbelow(1_000_000):06d}"
    db.add(
        AuthToken(
            user_id=user.id,
            token_hash=hash_magic_link_token(f"otp:{user.id}:{code}"),
            expires_at=now + timedelta(minutes=10),
            kind="otp",
        )
    )
    await db.commit()
    try:
        await send_otp_email(to_email=email, code=code)
    except Exception:
        log.exception("Failed to send OTP email")
    return OtpResponse(debug_code=code) if settings.DEBUG else OtpResponse()


@router.post("/verify-otp")
async def verify_otp(
    body: OtpVerifyRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> dict:
    email = body.email.lower().strip()
    generic = HTTPException(status_code=401, detail="Invalid or expired code")
    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user is None:
        raise generic

    now = datetime.now(timezone.utc)
    auth_token = (
        await db.execute(
            select(AuthToken)
            .where(AuthToken.user_id == user.id)
            .where(AuthToken.kind == "otp")
            .where(AuthToken.used_at.is_(None))
            .where(AuthToken.expires_at > now)
            .order_by(AuthToken.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if auth_token is None or auth_token.attempts >= 5:
        raise generic
    if auth_token.token_hash != hash_magic_link_token(f"otp:{user.id}:{body.code}"):
        auth_token.attempts += 1
        await db.commit()
        raise generic

    auth_token.used_at = now
    user.last_login_at = now
    _, session_token = await issue_session(db, user, auth_method="email_otp", request=request)
    await db.commit()
    _set_auth_cookie(response, session_token)
    return {"ok": True}


@router.post("/google")
async def google_sign_in(
    body: GoogleAuthRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        payload = await verify_google_credential(body.credential)
    except GoogleAuthError as exc:
        log.warning("Google sign-in rejected: %s", exc)
        raise HTTPException(status_code=401, detail="Google sign-in failed") from None

    email = str(payload["email"]).lower().strip()
    user = await _get_or_create_user(db, email)
    if user is None:
        raise HTTPException(status_code=500, detail="Signup is not configured")
    if not user.full_name and payload.get("name"):
        user.full_name = str(payload["name"])[:200]
    user.identity_provider = "google"
    user.last_login_at = datetime.now(timezone.utc)
    _, session_token = await issue_session(db, user, auth_method="google", request=request)
    await db.commit()
    _set_auth_cookie(response, session_token)
    return {"ok": True, "email": email}


@router.get("/config", response_model=AuthConfigResponse)
async def auth_config() -> AuthConfigResponse:
    return AuthConfigResponse(google_client_id=get_settings().GOOGLE_CLIENT_ID)


@router.get("/verify")
async def verify_magic_link(
    token: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    settings = get_settings()
    auth_token = (
        await db.execute(select(AuthToken).where(AuthToken.token_hash == hash_magic_link_token(token)))
    ).scalar_one_or_none()
    if auth_token is None:
        raise HTTPException(status_code=401, detail="Invalid token")
    now = datetime.now(timezone.utc)
    if auth_token.used_at is not None:
        raise HTTPException(status_code=401, detail="Token already used")
    if auth_token.expires_at < now:
        raise HTTPException(status_code=401, detail="Token expired")

    auth_token.used_at = now
    user = (await db.execute(select(User).where(User.id == auth_token.user_id))).scalar_one()
    user.last_login_at = now
    _, session_token = await issue_session(db, user, auth_method="magic_link", request=request)
    await db.commit()
    response = RedirectResponse(url=settings.FRONTEND_URL, status_code=302)
    _set_auth_cookie(response, session_token)
    return response


@router.post("/logout")
async def logout(
    response: Response,
    access_token: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Revoke the active server session when present, then clear the browser cookie."""
    settings = get_settings()
    if access_token:
        try:
            claims = decode_access_token_claims(access_token)
            if claims.session_id is not None:
                row = (
                    await db.execute(
                        select(ApplicationSession).where(
                            ApplicationSession.id == claims.session_id,
                            ApplicationSession.user_id == claims.user_id,
                        )
                    )
                ).scalar_one_or_none()
                if row is not None:
                    await revoke_session(
                        db,
                        row,
                        actor_id=claims.user_id,
                        reason="User signed out from this device.",
                    )
                    await db.commit()
        except Exception:
            # Logout remains idempotent and never reveals token validity.
            await db.rollback()
    response.delete_cookie(settings.SESSION_COOKIE_NAME)
    return {"ok": True}


@router.get("/me", response_model=CurrentUserResponse)
async def me(current_user: CurrentUser) -> CurrentUserResponse:
    return CurrentUserResponse(
        id=str(current_user.id),
        email=current_user.email,
        full_name=current_user.full_name,
        register_number=current_user.register_number,
        institution_name=current_user.institution.name,
        institution_short_name=current_user.institution.short_name,
        institution_id=str(current_user.institution_id),
    )


async def _get_or_create_user(db: AsyncSession, email: str) -> User | None:
    existing = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if existing is not None:
        return existing
    settings = get_settings()
    institutions = list(
        (await db.execute(select(Institution).where(Institution.is_active.is_(True)))).scalars()
    )
    domain = email.split("@", 1)[1].lower() if "@" in email else ""
    matching = next(
        (institution for institution in institutions if domain and domain in institution.email_domains_list),
        None,
    )
    if matching is None:
        matching = next(
            (
                institution
                for institution in institutions
                if institution.short_name == settings.DEFAULT_INSTITUTION_SHORT_NAME
            ),
            None,
        )
    if matching is None:
        return None
    user = User(email=email, institution_id=matching.id)
    db.add(user)
    await db.flush()
    return user


def _set_auth_cookie(response: Response, session_token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=session_token,
        max_age=settings.SESSION_ABSOLUTE_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=settings.ENV != "development",
        samesite="lax",
    )


def _redact(email: str) -> str:
    if "@" not in email:
        return "***"
    local, domain = email.split("@", 1)
    return f"{local[:2]}***@{domain}"
