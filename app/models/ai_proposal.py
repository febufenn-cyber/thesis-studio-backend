"""Structured AI proposals that require an explicit human decision."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class AIProposal(Base):
    __tablename__ = "ai_proposals"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("ai_runs.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    thread_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("ai_threads.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    based_on_document_version: Mapped[int] = mapped_column(Integer, nullable=False)
    task_mode: Mapped[str] = mapped_column(String(40), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="open")
    scope: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    explanation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    operations: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    human_edited_operations: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    assumptions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    unresolved_requirements: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    prompt_name: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    context_manifest: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    context_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    selected_operation_indexes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    decision_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    applied_command_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("document_commands.id", ondelete="SET NULL"), nullable=True
    )
    verifier_before: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    verifier_after: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("run_id", name="uq_ai_proposal_run"),
        Index("ix_ai_proposals_project_status", "project_id", "status"),
        Index("ix_ai_proposals_thread_created", "thread_id", "created_at"),
        Index("ix_ai_proposals_user_id", "user_id"),
    )
