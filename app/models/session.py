"""Legacy thesis coaching session model.

Phase 3 preserves these rows as conversation history, but the linked v2 Project
is the canonical source of truth for manuscript content and structured context.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


PHASE_INTAKE = "intake"


class ThesisSession(Base):
    __tablename__ = "sessions"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    institution_id_override: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("institutions.id", ondelete="SET NULL"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False, default="New thesis")
    phase: Mapped[str] = mapped_column(String(50), nullable=False, default=PHASE_INTAKE)

    # Historical coaching metadata. Once linked, these values may seed project
    # memory but never override the canonical Project document or policy.
    primary_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    subfield: Mapped[str | None] = mapped_column(String(100), nullable=True)
    framework: Mapped[str | None] = mapped_column(String(200), nullable=True)
    thesis_statement: Mapped[str | None] = mapped_column(Text, nullable=True)
    department_override: Mapped[str | None] = mapped_column(String(200), nullable=True)
    supervisor_full_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    supervisor_designation: Mapped[str | None] = mapped_column(String(200), nullable=True)
    hod_full_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    study_period: Mapped[str | None] = mapped_column(String(100), nullable=True)
    outline_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

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
