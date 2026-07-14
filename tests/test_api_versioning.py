"""API versioning: routers are reachable under /v1 while legacy root stays on."""

from __future__ import annotations


async def test_v1_and_legacy_both_serve(client) -> None:
    legacy = await client.get("/auth/config")
    versioned = await client.get("/v1/auth/config")
    assert legacy.status_code == 200
    assert versioned.status_code == 200
    # Same handler behind both mounts.
    assert legacy.json() == versioned.json()


async def test_app_level_routes_are_not_versioned(client) -> None:
    # /healthz is an application route, not a router, so it exists only at root.
    assert (await client.get("/healthz")).status_code == 200
    assert (await client.get("/v1/healthz")).status_code == 404
