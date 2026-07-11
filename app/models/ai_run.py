"""Durable, cancellable AI work units routed through the Phase 1 job queue."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class AIRun(Base):
    __tablename__ = "ai_runs"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    thread_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("ai_threads.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    request_message_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("ai_messages.id", ondelete="SET NULL"), nullable=True
    )
    client_request_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    task_mode: Mapped[str] = mapped_column(String(40), nullable=False)
    result_type: Mapped[str] = mapped_column(String(30), nullable=False, default="conversation")
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False, default="low")
    scope: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    requested_document_version: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt_name: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    context_manifest: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    context_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    progress: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("project_id", "client_request_id", name="uq_ai_run_client_request"),
        Index("ix_ai_runs_project_status", "project_id", "status"),
        Index("ix_ai_runs_thread_created", "thread_id", "created_at"),
        Index("ix_ai_runs_user_status", "user_id", "status"),
    )
