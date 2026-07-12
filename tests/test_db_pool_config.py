"""The DB connection pool must be env-configurable, defaults unchanged.

Tiny hosts (the owner-live 1 GB box) need pool_size=2/max_overflow=2; staging
and production must keep the historical 10/20. Both come from settings so a
single env override is the only change needed.
"""

from __future__ import annotations

from app.core.config import Settings


def _settings(**overrides) -> Settings:
    base = {
        "DATABASE_URL": "postgresql+asyncpg://u:p@localhost:5432/t",
        "JWT_SECRET": "x" * 64,
        "ANTHROPIC_API_KEY": "test-placeholder",
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)


def test_pool_defaults_preserve_prior_behaviour() -> None:
    s = _settings()
    assert s.DB_POOL_SIZE == 10
    assert s.DB_MAX_OVERFLOW == 20


def test_pool_can_be_shrunk_for_tiny_hosts() -> None:
    s = _settings(DB_POOL_SIZE=2, DB_MAX_OVERFLOW=2)
    assert s.DB_POOL_SIZE == 2
    assert s.DB_MAX_OVERFLOW == 2


def test_engine_uses_configured_pool_size() -> None:
    # The live engine wires settings -> create_async_engine; assert the pool
    # reflects the settings values rather than hardcoded constants.
    from app.db import session as session_module

    assert session_module.engine.pool.size() == session_module.settings.DB_POOL_SIZE
