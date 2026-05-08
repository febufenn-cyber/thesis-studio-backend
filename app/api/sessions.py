"""Sessions and messages routes.

Every endpoint here enforces the per-user isolation contract:
- All queries filter by user_id = current_user.id
- Cross-user access returns 404, not 403, to avoid leaking existence

The chat streaming endpoint (POST /sessions/{id}/messages) is in chat.py.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.db.deps import get_db
from app.models.message import Message
from app.models.session import ThesisSession
from app.schemas.session import (
    MessageResponse,
    SessionCreate,
    SessionResponse,
    SessionUpdate,
)


router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("", response_model=list[SessionResponse])
async def list_sessions(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> list[ThesisSession]:
    """List all (non-archived) thesis sessions belonging to the current user."""
    result = await db.execute(
        select(ThesisSession)
        .where(ThesisSession.user_id == current_user.id)
        .where(ThesisSession.archived.is_(False))
        .order_by(ThesisSession.updated_at.desc())
    )
    return list(result.scalars().all())


@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    body: SessionCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> ThesisSession:
    """Create a new thesis session for the current user."""
    session = ThesisSession(
        user_id=current_user.id,
        title=body.title or "New thesis",
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> ThesisSession:
    """Retrieve a single session. Returns 404 if not found OR not owned by current user."""
    return await _fetch_owned_session(db, session_id, current_user.id)


@router.patch("/{session_id}", response_model=SessionResponse)
async def update_session(
    session_id: UUID,
    body: SessionUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> ThesisSession:
    """Update fields on a session. Only fields present in the body are touched."""
    session = await _fetch_owned_session(db, session_id, current_user.id)

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(session, field, value)

    await db.commit()
    await db.refresh(session)
    return session


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_session(
    session_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Soft-delete a session by setting archived=True."""
    session = await _fetch_owned_session(db, session_id, current_user.id)
    session.archived = True
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{session_id}/messages", response_model=list[MessageResponse])
async def list_messages(
    session_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> list[Message]:
    """Return all messages for a session in chronological order.

    Auth check: verifies session ownership before returning messages.
    """
    # Verify ownership FIRST. This is the security boundary.
    await _fetch_owned_session(db, session_id, current_user.id)

    result = await db.execute(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at.asc())
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _fetch_owned_session(
    db: AsyncSession,
    session_id: UUID,
    user_id: UUID,
) -> ThesisSession:
    """Fetch a session, verifying it belongs to the given user.

    Returns 404 (not 403) when the session exists but belongs to someone else,
    so attackers can't enumerate session IDs.
    """
    result = await db.execute(
        select(ThesisSession)
        .where(ThesisSession.id == session_id)
        .where(ThesisSession.user_id == user_id)
        .where(ThesisSession.archived.is_(False))
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return session
