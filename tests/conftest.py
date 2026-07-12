"""Shared pytest fixtures for isolated PostgreSQL-backed API tests."""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Set test environment before importing modules that cache Settings.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://thesis:thesis@localhost:5433/thesis_studio_test",
)
os.environ.setdefault("ENV", "development")
os.environ.setdefault("JWT_SECRET", "a" * 64)
os.environ.setdefault("ANTHROPIC_API_KEY", "test-provider-key-placeholder")
os.environ.setdefault("DEFAULT_INSTITUTION_SHORT_NAME", "TU")
os.environ.setdefault("BILLING_PROVIDER", "test")
os.environ.setdefault(
    "BILLING_WEBHOOK_SECRET",
    "phase5-test-webhook-secret-at-least-32-characters",
)
os.environ.setdefault("MALWARE_SCAN_MODE", "disabled")
os.environ.setdefault("PRODUCTION_REQUIRE_MALWARE_SCAN", "false")

from app.core.security import create_access_token  # noqa: E402
from app.db.deps import get_db  # noqa: E402
from app.db.session import Base  # noqa: E402
from app.main import app  # noqa: E402
from app.models.institution import Institution  # noqa: E402
from app.models.user import User  # noqa: E402


_schema_ready = False


@pytest_asyncio.fixture
async def test_engine():
    """Per-test engine with no loop-crossing pooled connections."""
    from sqlalchemy.pool import NullPool

    from app.core.config import get_settings

    global _schema_ready
    engine = create_async_engine(
        get_settings().DATABASE_URL,
        echo=False,
        poolclass=NullPool,
    )
    if not _schema_ready:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        _schema_ready = True
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Function-scoped transaction rolled back after every test."""
    connection = await test_engine.connect()
    transaction = await connection.begin()
    factory = async_sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    session = factory()
    yield session
    await session.close()
    await transaction.rollback()
    await connection.close()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def test_institution(db_session: AsyncSession) -> Institution:
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
    return {"access_token": create_access_token(user.id)}
