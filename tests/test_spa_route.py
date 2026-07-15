"""Phase B SPA shell is served at /app and on client-side route paths."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_spa_root_served(client: AsyncClient) -> None:
    resp = await client.get("/app")
    assert resp.status_code == 200
    assert "/static/spa/assets/" in resp.text  # built shell references its bundle


async def test_spa_client_route_served(client: AsyncClient) -> None:
    # Deep links must return the shell so the client router can handle them.
    resp = await client.get("/app/projects/00000000-0000-0000-0000-000000000000/library")
    assert resp.status_code == 200
    assert 'id="root"' in resp.text
