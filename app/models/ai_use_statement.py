"""Generated AI Use Statement, bound to a document version and checksum.

A statement is a rendered disclosure (from ``app/provenance/templates``) pinned
to the document version and canonical checksum it was generated against, so an
exported/sealed disclosure can be shown to be current and tamper-evident.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class AIUseStatement(Base):
    """One generated AI Use Statement for a project at a document version."""

    __tablename__ = "ai_use_statements"
    __table_args__ = (
        Index("ix_ai_use_project_version", "project_id", "document_version"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_version: Mapped[int] = mapped_column(Integer, nullable=False)
    document_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    template_key: Mapped[str] = mapped_column(String(80), nullable=False)
    # document | section | block
    granularity: Mapped[str] = mapped_column(String(20), nullable=False, default="document")
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    rollup: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    generated_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
