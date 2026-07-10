"""Pytest fixtures.

Provides:
- An async DB session per test, rolled back at the end (no test pollution).
- A test client that uses the same session.
- Factories for institutions, users, and JWTs to make tests concise.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Set test env vars BEFORE importing anything that reads settings.
#
# DATABASE_URL default: port 5433 matches the committed docker-compose.yml
# postgres-test mapping (5433:5432).  Machine-level overrides (e.g. 5453 on
# this host via docker-compose.override.yml) win because setdefault only sets
# when the variable is absent.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://thesis:thesis@localhost:5433/thesis_studio_test")
os.environ.setdefault("JWT_SECRET", "a" * 64)
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-key-do-not-use")
os.environ.setdefault("DEFAULT_INSTITUTION_SHORT_NAME", "TU")

from app.core.security import create_access_token  # noqa: E402
from app.db.deps import get_db  # noqa: E402
from app.db.session import Base  # noqa: E402
from app.main import app  # noqa: E402
from app.models.institution import Institution  # noqa: E402
from app.models.user import User  # noqa: E402


# ---- Engine/session per-test ----
#
# Everything here is function-scoped on purpose. pytest-asyncio (0.25) gives
# each test its own event loop; asyncpg connections are loop-bound, so any
# engine (and its pooled connections) shared across tests raises
# "Future attached to a different loop". A per-test engine with NullPool
# (no pooled connections outliving the test) keeps every connection on the
# test's own loop. Engine creation is milliseconds; schema creation is
# guarded so it only runs once per session.

_schema_ready = False


@pytest_asyncio.fixture
async def test_engine():
    """Per-test engine (NullPool, loop-safe). Schema created on first use."""
    from sqlalchemy.pool import NullPool

    from app.core.config import get_settings

    global _schema_ready
    engine = create_async_engine(get_settings().DATABASE_URL, echo=False, poolclass=NullPool)

    if not _schema_ready:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        _schema_ready = True

    yield engine

    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Per-test DB session. Each test runs in its own transaction that's
    rolled back at the end so tests don't pollute each other.

    join_transaction_mode='create_savepoint' converts session commit() calls
    into savepoint releases so the outer connection-level transaction stays
    open and is rolled back at teardown — preventing test data from leaking
    across tests.
    """
    connection = await test_engine.connect()
    transaction = await connection.begin()
    factory = async_sessionmaker(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
    session = factory()

    yield session

    await session.close()
    await transaction.rollback()
    await connection.close()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Test HTTP client backed by the per-test DB session."""

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


# ---- Factories ----

@pytest_asyncio.fixture
async def test_institution(db_session: AsyncSession) -> Institution:
    """Create a single test institution that all test users belong to."""
    inst = Institution(
        name="Test University",
        short_name="TU",
        email_domains="test.edu",
        address="123 Test St, Testville",
        short_address="Testville",
        university_name="Test University",
        default_department="Department of English",
        department_aided=False,
    )
    db_session.add(inst)
    await db_session.commit()
    await db_session.refresh(inst)
    return inst


@pytest_asyncio.fixture
async def user_a(db_session: AsyncSession, test_institution: Institution) -> User:
    """User A — used in isolation tests as the 'rightful owner'."""
    user = User(
        email=f"alice-{uuid4().hex[:8]}@test.edu",
        full_name="Alice Test",
        institution_id=test_institution.id,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def user_b(db_session: AsyncSession, test_institution: Institution) -> User:
    """User B — used in isolation tests as the 'attacker'."""
    user = User(
        email=f"bob-{uuid4().hex[:8]}@test.edu",
        full_name="Bob Test",
        institution_id=test_institution.id,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


def auth_cookie(user: User) -> dict[str, str]:
    """Return a cookie dict for the given user, suitable for httpx requests."""
    return {"access_token": create_access_token(user.id)}
