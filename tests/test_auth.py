"""Auth flow tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import generate_magic_link_token, hash_magic_link_token
from app.models.auth_token import AuthToken
from app.models.institution import Institution
from app.models.user import User


pytestmark = pytest.mark.asyncio


async def test_request_link_for_matching_domain_assigns_that_institution(
    client: AsyncClient,
    db_session: AsyncSession,
    test_institution: Institution,
) -> None:
    """An email whose domain matches an institution's email_domains is assigned to it."""
    response = await client.post(
        "/auth/request-link",
        json={"email": "newstudent@test.edu"},
    )
    assert response.status_code == 200

    user_result = await db_session.execute(
        select(User).where(User.email == "newstudent@test.edu")
    )
    user = user_result.scalar_one_or_none()
    assert user is not None
    assert user.institution_id == test_institution.id

    token_result = await db_session.execute(
        select(AuthToken).where(AuthToken.user_id == user.id)
    )
    tokens = list(token_result.scalars().all())
    assert len(tokens) == 1


async def test_request_link_for_unmatched_domain_falls_back_to_default(
    client: AsyncClient,
    db_session: AsyncSession,
    test_institution: Institution,
) -> None:
    """An email whose domain doesn't match any institution lands on the default.

    `test_institution` has short_name 'TU', which conftest sets as
    DEFAULT_INSTITUTION_SHORT_NAME. So a gmail address should still create a
    user, assigned to the default institution.
    """
    response = await client.post(
        "/auth/request-link",
        json={"email": "stranger@gmail.com"},
    )
    assert response.status_code == 200

    user_result = await db_session.execute(
        select(User).where(User.email == "stranger@gmail.com")
    )
    user = user_result.scalar_one_or_none()
    assert user is not None
    assert user.institution_id == test_institution.id

    token_result = await db_session.execute(
        select(AuthToken).where(AuthToken.user_id == user.id)
    )
    assert len(list(token_result.scalars().all())) == 1


async def test_verify_with_valid_token_sets_cookie(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """A fresh, unused, unexpired token returns 302 with an access_token cookie."""
    raw_token, hashed = generate_magic_link_token()
    db_session.add(AuthToken(
        user_id=user_a.id,
        token_hash=hashed,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
    ))
    await db_session.commit()

    response = await client.get(
        f"/auth/verify?token={raw_token}",
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "access_token" in response.cookies


async def test_verify_with_expired_token_returns_401(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """An expired token must not authenticate."""
    raw_token, hashed = generate_magic_link_token()
    db_session.add(AuthToken(
        user_id=user_a.id,
        token_hash=hashed,
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),  # already expired
    ))
    await db_session.commit()

    response = await client.get(f"/auth/verify?token={raw_token}")
    assert response.status_code == 401


async def test_verify_with_used_token_returns_401(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """A token that's already been used cannot be reused."""
    raw_token, hashed = generate_magic_link_token()
    db_session.add(AuthToken(
        user_id=user_a.id,
        token_hash=hashed,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        used_at=datetime.now(timezone.utc),  # already consumed
    ))
    await db_session.commit()

    response = await client.get(f"/auth/verify?token={raw_token}")
    assert response.status_code == 401


async def test_verify_with_garbage_token_returns_401(client: AsyncClient) -> None:
    """A token that doesn't match anything in the DB returns 401."""
    response = await client.get("/auth/verify?token=this-is-not-a-real-token")
    assert response.status_code == 401


async def test_request_link_cooldown_suppresses_reissue(
    client: AsyncClient,
    db_session: AsyncSession,
    test_institution: Institution,
) -> None:
    """A second request within the cooldown window must not create a new token."""
    from sqlalchemy import func, select

    from app.models.auth_token import AuthToken
    from app.models.user import User

    email = f"cooldown-{uuid4().hex[:8]}@test.edu"

    first = await client.post("/auth/request-link", json={"email": email})
    assert first.status_code == 200
    second = await client.post("/auth/request-link", json={"email": email})
    assert second.status_code == 200  # anti-enumeration: response identical

    user_row = (
        await db_session.execute(select(User).where(User.email == email))
    ).scalar_one()
    count = (
        await db_session.execute(
            select(func.count()).select_from(AuthToken).where(
                AuthToken.user_id == user_row.id
            )
        )
    ).scalar_one()
    assert count == 1, "cooldown must suppress the second token"


async def test_otp_flow_end_to_end(
    client: AsyncClient,
    db_session: AsyncSession,
    test_institution: Institution,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Request OTP → wrong code 401 → right code sets a working session cookie."""
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "DEBUG", True)
    email = f"otp-{uuid4().hex[:8]}@test.edu"

    r = await client.post("/auth/request-otp", json={"email": email})
    assert r.status_code == 200
    code = r.json()["debug_code"]
    assert code and len(code) == 6

    r = await client.post("/auth/verify-otp", json={"email": email, "code": "000000" if code != "000000" else "111111"})
    assert r.status_code == 401

    r = await client.post("/auth/verify-otp", json={"email": email, "code": code})
    assert r.status_code == 200 and r.json()["ok"] is True
    cookie = r.cookies.get("access_token")
    assert cookie

    r = await client.get("/auth/me", cookies={"access_token": cookie})
    assert r.status_code == 200 and r.json()["email"] == email


async def test_otp_attempt_limit(
    client: AsyncClient,
    db_session: AsyncSession,
    test_institution: Institution,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After 5 wrong attempts even the correct code is rejected."""
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "DEBUG", True)
    email = f"otplim-{uuid4().hex[:8]}@test.edu"
    r = await client.post("/auth/request-otp", json={"email": email})
    code = r.json()["debug_code"]
    wrong = "999999" if code != "999999" else "888888"
    for _ in range(5):
        r = await client.post("/auth/verify-otp", json={"email": email, "code": wrong})
        assert r.status_code == 401
    r = await client.post("/auth/verify-otp", json={"email": email, "code": code})
    assert r.status_code == 401


async def test_google_sign_in(
    client: AsyncClient,
    db_session: AsyncSession,
    test_institution: Institution,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A verified Google credential creates the user and sets the cookie."""
    email = f"goog-{uuid4().hex[:8]}@gmail.com"

    async def _fake_verify(credential: str) -> dict:
        assert credential == "fake-credential-token-abc"
        return {"email": email, "email_verified": True, "name": "Goo Gle", "sub": "1"}

    monkeypatch.setattr("app.api.auth.verify_google_credential", _fake_verify)
    r = await client.post("/auth/google", json={"credential": "fake-credential-token-abc"})
    assert r.status_code == 200 and r.json()["ok"] is True
    cookie = r.cookies.get("access_token")
    r = await client.get("/auth/me", cookies={"access_token": cookie})
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == email and body["full_name"] == "Goo Gle"


async def test_google_sign_in_rejects_bad_credential(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.google_auth import GoogleAuthError

    async def _fail(credential: str) -> dict:
        raise GoogleAuthError("nope")

    monkeypatch.setattr("app.api.auth.verify_google_credential", _fail)
    r = await client.post("/auth/google", json={"credential": "x" * 30})
    assert r.status_code == 401
