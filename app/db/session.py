"""Database session and engine setup.

This module creates the async SQLAlchemy engine and session factory.
Routes get sessions via the `get_db` dependency in `app.db.deps`.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings


class Base(DeclarativeBase):
    """SQLAlchemy declarative base. All ORM models inherit from this."""


settings = get_settings()

# Engine: holds the connection pool. One per process.
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

# Session factory: creates new AsyncSession instances on demand.
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,  # don't lazy-load after commit; fine for our use
    autoflush=False,
)
