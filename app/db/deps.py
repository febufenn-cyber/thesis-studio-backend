"""FastAPI dependencies for database access."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Yield a database session scoped to one HTTP request.

    Used as a FastAPI dependency:

        @router.get("/foo")
        async def foo(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        # Commit is the route handler's responsibility — explicit > implicit.
