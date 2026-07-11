"""Phase 4 snapshot-bound academic review and approval models."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class ReviewCycle(Base):
    __tablename__ = "review_cycles"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    snapshot_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("document_snapshots.id", ondelete="RESTRICT"), nullable=False
    )
    cycle_number: Mapped[int] = mapped_column(Integer, nullable=False)
    scope_type: Mapped[str] = mapped_column(String(24), nullable=False)
    scope_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    submitted_document_version: Mapped[int] = mapped_column(Integer, nullable=False)
    submitted_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    submitted_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    reviewer_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="submitted")
    decision: Mapped[str | None] = mapped_column(String(40), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resubmitted_from_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("review_cycles.id", ondelete="SET NULL"), nullable=True
    )
    superseded_by_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("review_cycles.id", ondelete="SET NULL"), nullable=True
    )
    current_document_version_at_decision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("project_id", "cycle_number", name="uq_review_cycle_number"),
        Index("ix_review_cycle_reviewer_queue", "reviewer_id", "status", "deadline"),
        Index("ix_review_cycle_project_scope", "project_id", "scope_type", "scope_id"),
    )


class CollaborationComment(Base):
    __tablename__ = "collaboration_comments"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    review_cycle_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("review_cycles.id", ondelete="CASCADE"), nullable=True
    )
    author_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    parent_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("collaboration_comments.id", ondelete="CASCADE"), nullable=True
    )
    anchor_type: Mapped[str] = mapped_column(String(30), nullable=False)
    anchor: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    selected_text_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_version: Mapped[int] = mapped_column(Integer, nullable=False)
    anchor_state: Mapped[str] = mapped_column(String(24), nullable=False, default="current")
    body: Mapped[str] = mapped_column(Text, nullable=False)
    visibility: Mapped[str] = mapped_column(String(30), nullable=False, default="project_members")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="open")
    assigned_to: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolved_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_comment_project_status", "project_id", "status", "created_at"),
        Index("ix_comment_cycle", "review_cycle_id", "created_at"),
        Index("ix_comment_assignee", "assigned_to", "status"),
    )


class HumanSuggestion(Base):
    __tablename__ = "human_suggestions"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    review_cycle_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("review_cycles.id", ondelete="CASCADE"), nullable=True
    )
    author_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    target_block_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    based_on_document_version: Mapped[int] = mapped_column(Integer, nullable=False)
    before_block: Mapped[dict] = mapped_column(JSONB, nullable=False)
    proposed_operation: Mapped[dict] = mapped_column(JSONB, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    student_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decision_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    applied_command_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("document_commands.id", ondelete="SET NULL"), nullable=True
    )
    manual_resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_human_suggestion_project_status", "project_id", "status", "created_at"),
        Index("ix_human_suggestion_block", "target_block_id", "status"),
    )


class ApprovalRecord(Base):
    __tablename__ = "approval_records"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    review_cycle_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("review_cycles.id", ondelete="SET NULL"), nullable=True
    )
    snapshot_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("document_snapshots.id", ondelete="RESTRICT"), nullable=False
    )
    dimension: Mapped[str] = mapped_column(String(30), nullable=False)
    scope_type: Mapped[str] = mapped_column(String(24), nullable=False)
    scope_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    decision: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    approved_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    document_version: Mapped[int] = mapped_column(Integer, nullable=False)
    document_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    invalidated_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    invalidated_by_event_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("events.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_approval_project_dimension", "project_id", "dimension", "status"),
        Index("ix_approval_scope", "project_id", "scope_type", "scope_id", "status"),
    )


class SupervisorInstruction(Base):
    __tablename__ = "supervisor_instructions"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    author_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    scope_type: Mapped[str] = mapped_column(String(24), nullable=False, default="project")
    scope_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    instruction_type: Mapped[str] = mapped_column(String(50), nullable=False)
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="mandatory")
    text: Mapped[str] = mapped_column(Text, nullable=False)
    structured: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fulfilled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    superseded_by_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("supervisor_instructions.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_instruction_project_status", "project_id", "status", "priority"),)


class Attestation(Base):
    __tablename__ = "attestations"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    submission_package_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("submission_packages.id", ondelete="CASCADE", use_alter=True), nullable=True
    )
    attestation_type: Mapped[str] = mapped_column(String(50), nullable=False)
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    statement_version: Mapped[str] = mapped_column(String(40), nullable=False)
    statement_text: Mapped[str] = mapped_column(Text, nullable=False)
    accepted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    context: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "submission_package_id", "attestation_type", "user_id", name="uq_attestation_package_type_user"
        ),
    )
