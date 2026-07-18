"""Legacy compile quarantine.

The chat->compile path is disabled by default (LEGACY_COMPILE_ENABLED=False) so
its unverified-citation output cannot be produced in production. The conftest
enables it for the existing compile suite; here we assert both sides of the gate.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.config import get_settings
from app.models.session import ThesisSession
from tests.conftest import auth_cookie

pytestmark = pytest.mark.asyncio


async def test_compile_returns_404_when_quarantined(
    client: AsyncClient, user_a, monkeypatch
) -> None:
    monkeypatch.setattr(get_settings(), "LEGACY_COMPILE_ENABLED", False)
    response = await client.post(
        f"/sessions/{uuid4()}/compile", cookies=auth_cookie(user_a)
    )
    assert response.status_code == 404
    assert "not enabled" in response.json()["detail"].lower()


async def test_compile_gate_opens_when_enabled(
    client: AsyncClient, db_session, user_a, monkeypatch
) -> None:
    monkeypatch.setattr(get_settings(), "LEGACY_COMPILE_ENABLED", True)
    session = ThesisSession(user_id=user_a.id, title="Quarantine gate")
    db_session.add(session)
    await db_session.commit()
    response = await client.post(
        f"/sessions/{session.id}/compile", cookies=auth_cookie(user_a)
    )
    # Past the gate: the next guard (no assistant reply yet) returns 409.
    assert response.status_code == 409


async def test_console_layer_absent_when_quarantined(monkeypatch) -> None:
    """With LEGACY_CONSOLE_ENABLED=False the /legacy route and the phase-1
    console's API surface (sessions, chat) do not mount at all: 404, not 401."""
    import httpx
    from httpx import ASGITransport

    from app.core.config import get_settings as gs
    from app.main import create_app

    monkeypatch.setattr(gs(), "LEGACY_CONSOLE_ENABLED", False)
    app = create_app()
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        assert (await c.get("/legacy")).status_code == 404
        # Unmounted router → 404. (Mounted-but-unauthenticated would be 401.)
        assert (await c.get("/sessions")).status_code == 404
        # The studio and SPA are untouched by the quarantine.
        assert (await c.get("/")).status_code == 200
        assert (await c.get("/app")).status_code == 200


async def test_console_layer_mounts_when_enabled(monkeypatch) -> None:
    import httpx
    from httpx import ASGITransport

    from app.core.config import get_settings as gs
    from app.main import create_app

    monkeypatch.setattr(gs(), "LEGACY_CONSOLE_ENABLED", True)
    app = create_app()
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        assert (await c.get("/legacy")).status_code == 200
        # Mounted and auth-guarded: unauthenticated is 401, not 404.
        assert (await c.get("/sessions")).status_code == 401
