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
