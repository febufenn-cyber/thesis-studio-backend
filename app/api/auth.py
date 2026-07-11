"""Authentication routes: magic-link login flow.

Flow:
1. POST /auth/request-link {email}  → email sent with one-time link
2. GET  /auth/verify?token=...      → JWT cookie set, redirect to frontend
3. GET  /me                         → returns current user

Security notes:
- Email enumeration is prevented: /auth/request-link returns the same response
  whether the email exists or not.
- Tokens are SHA-256 hashed before storage. The raw token only travels through
  email and the verify URL.
- Tokens are single-use (used_at marks consumption) and expire (default 15 min).
- Signup is open: any email domain may request a magic link. Domain is used as
  a hint to assign an institution; emails not matching any institution land at
  DEFAULT_INSTITUTION_SHORT_NAME. Per-session override is available on
  ThesisSession.institution_id_override for users whose email doesn't reflect
  their actual institution.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    generate_magic_link_token,
    hash_magic_link_token,
)
from app.db.deps import get_db
from app.models.auth_token import AuthToken
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
async def request_magic_link(
    body: MagicLinkRequest,
    db: AsyncSession = Depends(get_db),
) -> MagicLinkResponse:
    """Send a magic-link email. Open signup — any email domain accepted.

    Returns the same response regardless of whether the email is valid or
    registered, to prevent email enumeration. Errors are logged server-side.
    """
    settings = get_settings()
    email = body.email.lower().strip()

    # Open signup. New users get an institution either by domain match or by
    # falling back to DEFAULT_INSTITUTION_SHORT_NAME. None is returned only on
    # system misconfiguration (default institution missing).
    user = await _get_or_create_user(db, email)
    if user is None:
        log.error(
            "Magic-link request failed: default institution '%s' not found",
            settings.DEFAULT_INSTITUTION_SHORT_NAME,
        )
        return MagicLinkResponse()

    # Cooldown: if an unused, unexpired token was issued in the last few
    # minutes, silently skip issuing another. Caps the email-spam / row-flood
    # rate an attacker can drive against a victim address, at the cost of a
    # short wait before a legitimate "resend". Response stays identical to
    # preserve anti-enumeration.
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
        log.info("Magic-link cooldown active for user %s — not reissuing", user.id)
        return MagicLinkResponse()

    # Generate a fresh token, store the hash, send the raw token in the URL.
    raw_token, hashed_token = generate_magic_link_token()
    expires_at = now + timedelta(minutes=settings.MAGIC_LINK_EXPIRY_MINUTES)

    db.add(AuthToken(
        user_id=user.id,
        token_hash=hashed_token,
        expires_at=expires_at,
    ))
    await db.commit()

    link_url = settings.magic_link_url_template.format(token=raw_token)

    try:
        await send_magic_link_email(to_email=email, link_url=link_url)
    except Exception as exc:
        # Don't surface email failures to the caller — that would leak info.
        log.exception("Failed to send magic-link email: %s", exc)

    # In DEBUG (local dev), return the link directly so the UI can render
    # a one-click sign-in button. Production never returns the link.
    if settings.DEBUG:
        return MagicLinkResponse(magic_link=link_url)
    return MagicLinkResponse()


@router.post("/request-otp", response_model=OtpResponse)
async def request_otp(
    body: OtpRequest,
    db: AsyncSession = Depends(get_db),
) -> OtpResponse:
    """Email a 6-digit sign-in code. Opaque response (anti-enumeration)."""
    import secrets

    settings = get_settings()
    email = body.email.lower().strip()

    user = await _get_or_create_user(db, email)
    if user is None:
        log.error("OTP request failed: default institution missing")
        return OtpResponse()

    now = datetime.now(timezone.utc)
    # Cooldown: one live code per minute per account.
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
    db.add(AuthToken(
        user_id=user.id,
        token_hash=hash_magic_link_token(f"otp:{user.id}:{code}"),
        expires_at=now + timedelta(minutes=10),
        kind="otp",
    ))
    await db.commit()

    try:
        await send_otp_email(to_email=email, code=code)
    except Exception:
        log.exception("Failed to send OTP email")

    if settings.DEBUG:
        return OtpResponse(debug_code=code)
    return OtpResponse()


@router.post("/verify-otp")
async def verify_otp(
    body: OtpVerifyRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Exchange email + 6-digit code for an authenticated session cookie."""
    email = body.email.lower().strip()
    generic = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired code",
    )

    user = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if user is None:
        raise generic

    now = datetime.now(timezone.utc)
    token = (
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
    if token is None or token.attempts >= 5:
        raise generic

    if token.token_hash != hash_magic_link_token(f"otp:{user.id}:{body.code}"):
        token.attempts += 1
        await db.commit()
        raise generic

    token.used_at = now
    user.last_login_at = now
    await db.commit()

    _set_auth_cookie(response, create_access_token(user.id))
    return {"ok": True}


@router.post("/google")
async def google_sign_in(
    body: GoogleAuthRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Sign in with a Google Identity Services ID token."""
    try:
        payload = await verify_google_credential(body.credential)
    except GoogleAuthError as exc:
        log.warning("Google sign-in rejected: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google sign-in failed",
        ) from None

    email = str(payload["email"]).lower().strip()
    user = await _get_or_create_user(db, email)
    if user is None:
        log.error("Google sign-in failed: default institution missing")
        raise HTTPException(status_code=500, detail="Signup is not configured")

    # Best-effort profile enrichment on first login.
    if not user.full_name and payload.get("name"):
        user.full_name = str(payload["name"])[:200]
    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()

    _set_auth_cookie(response, create_access_token(user.id))
    return {"ok": True, "email": email}


@router.get("/config", response_model=AuthConfigResponse)
async def auth_config() -> AuthConfigResponse:
    """Public auth configuration for the SPA (which sign-in methods exist)."""
    return AuthConfigResponse(google_client_id=get_settings().GOOGLE_CLIENT_ID)


@router.get("/verify")
async def verify_magic_link(
    token: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Exchange a magic-link token for an authenticated session.

    Sets an HTTP-only JWT cookie and redirects to the frontend.
    Single-use: the token's used_at field is set on success.
    """
    settings = get_settings()
    hashed = hash_magic_link_token(token)

    result = await db.execute(
        select(AuthToken).where(AuthToken.token_hash == hashed)
    )
    auth_token = result.scalar_one_or_none()

    if auth_token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    now = datetime.now(timezone.utc)
    if auth_token.used_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token already used",
        )
    if auth_token.expires_at < now:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
        )

    # Mark the token consumed and update last_login on the user.
    auth_token.used_at = now
    user_result = await db.execute(select(User).where(User.id == auth_token.user_id))
    user = user_result.scalar_one()
    user.last_login_at = now
    await db.commit()

    # Issue a long-lived JWT and set as HTTP-only cookie.
    jwt_token = create_access_token(user.id)
    response = RedirectResponse(url=settings.FRONTEND_URL, status_code=302)
    _set_auth_cookie(response, jwt_token)
    return response


@router.post("/logout")
async def logout(response: Response) -> dict:
    """Clear the JWT cookie. Tokens themselves can't be revoked server-side
    in a stateless JWT scheme — they expire when they expire. For now this
    is fine; we can add a revocation list if needed."""
    response.delete_cookie("access_token")
    return {"ok": True}


@router.get("/me", response_model=CurrentUserResponse)
async def me(current_user: CurrentUser) -> CurrentUserResponse:
    """Return the currently authenticated user."""
    return CurrentUserResponse(
        id=str(current_user.id),
        email=current_user.email,
        full_name=current_user.full_name,
        register_number=current_user.register_number,
        institution_name=current_user.institution.name,
        institution_short_name=current_user.institution.short_name,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_or_create_user(db: AsyncSession, email: str) -> User | None:
    """Look up a user by email, or create one with institution assigned by hint.

    Resolution order for new users:
        1. If an active institution's email_domains includes the email's domain,
           assign that institution.
        2. Otherwise, look up the institution whose short_name equals
           DEFAULT_INSTITUTION_SHORT_NAME and assign that.

    Returns None only if both resolution steps fail (system misconfigured: the
    default institution doesn't exist).
    """
    result = await db.execute(select(User).where(User.email == email))
    existing = result.scalar_one_or_none()
    if existing is not None:
        return existing

    settings = get_settings()
    inst_result = await db.execute(select(Institution).where(Institution.is_active.is_(True)))
    institutions = list(inst_result.scalars())

    domain = email.split("@", 1)[1].lower() if "@" in email else ""
    matching_inst = next(
        (i for i in institutions if domain and domain in i.email_domains_list),
        None,
    )

    if matching_inst is None:
        matching_inst = next(
            (i for i in institutions if i.short_name == settings.DEFAULT_INSTITUTION_SHORT_NAME),
            None,
        )

    if matching_inst is None:
        return None

    user = User(email=email, institution_id=matching_inst.id)
    db.add(user)
    await db.flush()
    return user


def _set_auth_cookie(response: Response, jwt_token: str) -> None:
    """Attach the session JWT as an HTTP-only cookie (shared by all login flows)."""
    settings = get_settings()
    response.set_cookie(
        key="access_token",
        value=jwt_token,
        max_age=settings.JWT_EXPIRY_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=settings.ENV != "development",
        samesite="lax",
    )


def _redact(email: str) -> str:
    """Redact most of an email for logging purposes."""
    if "@" not in email:
        return "***"
    local, domain = email.split("@", 1)
    return f"{local[:2]}***@{domain}"
