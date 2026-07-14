"""Per-field provenance for resolver-applied Source values.

Every field the resolver writes back onto a Source records which authority
supplied it and at what confidence, so a human can audit or override any
auto-resolved value. Fields left as ``[VERIFY]`` (never resolved) get no row.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class SourceFieldProvenance(Base):
    """One (source, field) resolution provenance row."""

    __tablename__ = "source_field_provenance"
    __table_args__ = (
        UniqueConstraint("source_id", "field_name", name="uq_source_field_provenance"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    source_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    field_name: Mapped[str] = mapped_column(String(60), nullable=False)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    authority: Mapped[str] = mapped_column(String(30), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    resolution_record_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("resolution_records.id", ondelete="SET NULL"),
        nullable=True,
    )
    applied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
