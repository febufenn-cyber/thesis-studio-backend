"""Supervision & committee models (docs/LLD.md 3.6).

``committee_memberships`` refine supervisor-class seats into committee positions;
``block_comments`` anchor feedback to a canonical block id (surviving re-render,
because the anchor is the block UUID, not a text offset).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class CommitteeMembership(Base):
    __tablename__ = "committee_memberships"
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_committee_member_user"),
        Index("ix_committee_project_role", "project_id", "committee_role", "status"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    committee_role: Mapped[str] = mapped_column(String(32), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    voting: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    content_access: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    assigned_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class BlockComment(Base):
    __tablename__ = "block_comments"
    __table_args__ = (
        Index("ix_block_comment_block", "project_id", "canonical_block_id", "status"),
        Index("ix_block_comment_thread", "thread_root_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    canonical_block_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    scope_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    thread_root_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("block_comments.id", ondelete="CASCADE"), nullable=True
    )
    author_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    committee_role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    block_text_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_seen_document_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    anchor_state: Mapped[str] = mapped_column(String(24), nullable=False, default="current")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="open")
    resolved_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
