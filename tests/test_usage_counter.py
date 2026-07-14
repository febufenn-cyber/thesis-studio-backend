"""Atomic quota reservation under concurrency.

These tests open independent connections from a NullPool engine (real connections,
real commits) so the reservations genuinely contend at the database level — the
whole point of the counter is that N concurrent reservers cannot all slip under
the limit, which a single shared/savepointed session could not demonstrate. A
per-test engine is used (not the app's module-level sessionmaker) so every
connection is bound to the running test's event loop.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from uuid import uuid4

import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.commercial.entitlements import (
    EntitlementContext,
    EntitlementQuotaExceeded,
    release_usage,
    reserve_usage,
)
from app.core.config import get_settings
from app.models.commercial import UsageCounter

# All-NULL scope avoids FK requirements on institutions/users/projects; a unique
# entitlement key isolates each test's counter row.
_CTX = EntitlementContext(institution_id=None, user_id=None, project_id=None)


@pytest_asyncio.fixture
async def counter_sessions(test_engine):
    """A sessionmaker over a NullPool engine bound to this test's event loop.

    Depends on the conftest ``test_engine`` fixture only to guarantee the schema
    (including usage_counters) is created; the concurrency work uses independent
    connections from this dedicated engine so reservations truly contend.
    """
    engine = create_async_engine(get_settings().DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _reserve_once(factory, key: str, limit: int) -> bool:
    async with factory() as session:
        try:
            await reserve_usage(session, _CTX, key, limit, quantity=1)
            await session.commit()
            return True
        except EntitlementQuotaExceeded:
            await session.rollback()
            return False


async def _cleanup(factory, key: str) -> None:
    async with factory() as session:
        await session.execute(delete(UsageCounter).where(UsageCounter.entitlement_key == key))
        await session.commit()


async def test_concurrent_reservations_cannot_exceed_limit(counter_sessions) -> None:
    key = f"test.metered.{uuid4().hex}"
    limit = 3
    try:
        results = await asyncio.gather(
            *[_reserve_once(counter_sessions, key, limit) for _ in range(12)]
        )
        assert sum(results) == limit  # exactly `limit` win, the rest are rejected

        async with counter_sessions() as session:
            row = (
                await session.execute(
                    select(UsageCounter).where(UsageCounter.entitlement_key == key)
                )
            ).scalar_one()
            assert row.consumed == Decimal(limit)
    finally:
        await _cleanup(counter_sessions, key)


async def test_release_frees_a_slot(counter_sessions) -> None:
    key = f"test.metered.{uuid4().hex}"
    limit = 2
    try:
        assert await _reserve_once(counter_sessions, key, limit) is True
        assert await _reserve_once(counter_sessions, key, limit) is True
        assert await _reserve_once(counter_sessions, key, limit) is False  # full

        async with counter_sessions() as session:
            await release_usage(session, _CTX, key, quantity=1)
            await session.commit()

        assert await _reserve_once(counter_sessions, key, limit) is True  # slot freed
    finally:
        await _cleanup(counter_sessions, key)


async def test_quantity_larger_than_limit_is_rejected(counter_sessions) -> None:
    key = f"test.metered.{uuid4().hex}"
    try:
        async with counter_sessions() as session:
            raised = False
            try:
                await reserve_usage(session, _CTX, key, 3, quantity=5)
            except EntitlementQuotaExceeded:
                raised = True
            await session.rollback()
            assert raised
    finally:
        await _cleanup(counter_sessions, key)
