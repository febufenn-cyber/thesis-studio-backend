"""Source model — Citation Registry entry with import and verification provenance."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class Source(Base):
    """One citation-registry source.

    Parsed fields never replace the exact original bibliography entry. The
    provenance columns make every structured value traceable to an immutable
    manuscript revision and parser version.
    """

    __tablename__ = "sources"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    fields: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    raw_entry: Mapped[str | None] = mapped_column(Text, nullable=True)
    parse_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="structured_with_review"
    )
    source_paragraph_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    import_revision_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("manuscript_revisions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    parser_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    parser_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    identifiers: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    verify_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    verification_method: Mapped[str | None] = mapped_column(String(40), nullable=True)

    consulted_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
