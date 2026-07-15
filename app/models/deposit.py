"""External repository deposits (docs/LLD_MISSING_FEATURES.md MF3)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class Deposit(Base):
    __tablename__ = "deposits"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    export_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("exports.id", ondelete="SET NULL"), nullable=True
    )
    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    target: Mapped[str] = mapped_column(String(20), nullable=False)  # zenodo | dspace
    # pending | draft_created | files_uploaded | published | failed
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    remote_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    doi: Mapped[str | None] = mapped_column(String(120), nullable=True)
    landing_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    orcid: Mapped[str | None] = mapped_column(String(19), nullable=True)
    sandbox: Mapped[bool] = mapped_column(default=True, nullable=False)
    response: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
