"""Pydantic schemas for the auth endpoints."""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class MagicLinkRequest(BaseModel):
    """POST /auth/request-link body."""

    email: EmailStr = Field(..., description="Institutional email address")


class MagicLinkResponse(BaseModel):
    """POST /auth/request-link response — opaque success regardless of email validity.

    `magic_link` is only populated when DEBUG=true (local dev), so the frontend
    can render a clickable sign-in button and skip the email/log dance. Never
    populated in production.
    """

    ok: bool = True
    message: str = "If the email is registered, a sign-in link has been sent."
    magic_link: str | None = None


class CurrentUserResponse(BaseModel):
    """GET /me response."""

    id: str
    email: str
    full_name: str | None
    register_number: str | None
    institution_name: str
    institution_short_name: str
    institution_id: str


class OtpRequest(BaseModel):
    """POST /auth/request-otp body."""

    email: EmailStr


class OtpVerifyRequest(BaseModel):
    """POST /auth/verify-otp body."""

    email: EmailStr
    code: str = Field(..., min_length=6, max_length=6, pattern=r"^[0-9]{6}$")


class OtpResponse(BaseModel):
    """POST /auth/request-otp response — opaque success (anti-enumeration).

    `debug_code` is only populated when DEBUG=true so local dev works with
    no email provider. Never populated in production.
    """

    ok: bool = True
    message: str = "If the email is registered, a sign-in code has been sent."
    debug_code: str | None = None


class GoogleAuthRequest(BaseModel):
    """POST /auth/google body — the Google Identity Services ID token."""

    credential: str = Field(..., min_length=20)


class AuthConfigResponse(BaseModel):
    """GET /auth/config response — public auth configuration for the SPA."""

    google_client_id: str = ""
