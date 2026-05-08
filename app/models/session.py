"""Thesis session model — one row per thesis project a student is working on."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


# Workflow phase as a string (not an enum) so we can add phases without migrations.
# Valid values: 'intake', 'topic', 'framework', 'sources', 'outline', 'drafting',
# 'revision', 'compile'.
PHASE_INTAKE = "intake"


class ThesisSession(Base):
    """A single thesis project belonging to one user.

    Named `ThesisSession` (not `Session`) to avoid collision with SQLAlchemy's
    `Session` class. Table name is `sessions` for clarity in SQL.
    """

    __tablename__ = "sessions"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    title: Mapped[str] = mapped_column(String(300), nullable=False, default="New thesis")

    # Workflow tracking
    phase: Mapped[str] = mapped_column(String(50), nullable=False, default=PHASE_INTAKE)

    # Thesis metadata captured during the dialogue
    primary_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    subfield: Mapped[str | None] = mapped_column(String(100), nullable=True)
    framework: Mapped[str | None] = mapped_column(String(200), nullable=True)
    thesis_statement: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Front-matter overrides — students can customize per-session.
    # If null, the formatter falls back to the institution defaults.
    department_override: Mapped[str | None] = mapped_column(String(200), nullable=True)
    supervisor_full_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    supervisor_designation: Mapped[str | None] = mapped_column(String(200), nullable=True)
    hod_full_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    study_period: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Outline accumulated during the dialogue (populated near the end of phase 5)
    outline_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Bookkeeping
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
