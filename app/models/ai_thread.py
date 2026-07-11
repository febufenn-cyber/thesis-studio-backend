"""Project-scoped AI conversation threads for the grounded thesis partner."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class AIThread(Base):
    """A project-linked conversation whose canonical source of truth is Project.

    A thread may reference a legacy coaching session for historical continuity,
    but Phase 3 context is always compiled from the canonical project and the
    explicitly selected scope. Raw legacy session fields never override it.
    """

    __tablename__ = "ai_threads"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    legacy_session_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False, default="Robofox Scholar")
    scope: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    private: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_ai_threads_project_updated", "project_id", "updated_at"),
        Index("ix_ai_threads_user_id", "user_id"),
        Index("ix_ai_threads_legacy_session_id", "legacy_session_id"),
    )
