"""Auth flow tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

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
