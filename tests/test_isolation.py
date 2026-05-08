"""Per-user isolation tests.

THESE TESTS MUST PASS ON EVERY COMMIT.

They verify that user A cannot read, modify, or delete user B's data — the
foundational security boundary of the entire system. If any of these fail,
the breach is fundamental and the system must not deploy.

The expected outcome of any cross-user access attempt is HTTP 404 (not 403),
because 403 leaks the existence of the resource.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session import ThesisSession
from app.models.user import User
from tests.conftest import auth_cookie


pytestmark = pytest.mark.asyncio


async def test_list_sessions_returns_only_own_sessions(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
) -> None:
    """User A should never see User B's sessions in the list endpoint."""
    # Create one session per user.
    db_session.add_all([
        ThesisSession(user_id=user_a.id, title="Alice's thesis"),
        ThesisSession(user_id=user_b.id, title="Bob's thesis"),
    ])
    await db_session.commit()

    # User A lists their sessions — should see exactly one.
    response = await client.get("/sessions", cookies=auth_cookie(user_a))
    assert response.status_code == 200
    sessions = response.json()
    assert len(sessions) == 1
    assert sessions[0]["title"] == "Alice's thesis"


async def test_get_other_users_session_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
) -> None:
    """User A trying to read User B's session must get 404, not 403 or 200."""
    bobs_session = ThesisSession(user_id=user_b.id, title="Bob's thesis")
    db_session.add(bobs_session)
    await db_session.commit()
    await db_session.refresh(bobs_session)

    response = await client.get(
        f"/sessions/{bobs_session.id}",
        cookies=auth_cookie(user_a),
    )
    assert response.status_code == 404, (
        "Cross-user GET must return 404 (not 403) to avoid leaking existence"
    )


async def test_patch_other_users_session_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
) -> None:
    """User A must not be able to modify User B's session."""
    bobs_session = ThesisSession(user_id=user_b.id, title="Bob's thesis")
    db_session.add(bobs_session)
    await db_session.commit()
    await db_session.refresh(bobs_session)

    response = await client.patch(
        f"/sessions/{bobs_session.id}",
        json={"title": "Hacked"},
        cookies=auth_cookie(user_a),
    )
    assert response.status_code == 404


async def test_delete_other_users_session_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
) -> None:
    """User A must not be able to delete User B's session."""
    bobs_session = ThesisSession(user_id=user_b.id, title="Bob's thesis")
    db_session.add(bobs_session)
    await db_session.commit()
    await db_session.refresh(bobs_session)

    response = await client.delete(
        f"/sessions/{bobs_session.id}",
        cookies=auth_cookie(user_a),
    )
    assert response.status_code == 404


async def test_list_other_users_messages_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
) -> None:
    """User A must not be able to read User B's chat messages."""
    bobs_session = ThesisSession(user_id=user_b.id, title="Bob's thesis")
    db_session.add(bobs_session)
    await db_session.commit()
    await db_session.refresh(bobs_session)

    response = await client.get(
        f"/sessions/{bobs_session.id}/messages",
        cookies=auth_cookie(user_a),
    )
    assert response.status_code == 404


async def test_unauthenticated_request_returns_401(client: AsyncClient) -> None:
    """No JWT cookie → 401 Unauthorized."""
    response = await client.get("/sessions")
    assert response.status_code == 401


async def test_invalid_jwt_returns_401(client: AsyncClient) -> None:
    """Garbage JWT → 401."""
    response = await client.get(
        "/sessions",
        cookies={"access_token": "not.a.valid.jwt"},
    )
    assert response.status_code == 401


async def test_nonexistent_session_returns_404(
    client: AsyncClient,
    user_a: User,
) -> None:
    """Even with valid auth, a session that doesn't exist returns 404."""
    response = await client.get(
        "/sessions/00000000-0000-0000-0000-000000000000",
        cookies=auth_cookie(user_a),
    )
    assert response.status_code == 404
