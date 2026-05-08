"""Usage event model — one row per Anthropic API call for cost tracking."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


# Event type values
EVENT_TYPE_CHAT = "chat"
EVENT_TYPE_COMPILE = "compile_doc"
EVENT_TYPE_UTILITY = "utility"


class UsageEvent(Base):
    """One row per Anthropic API call.

    Required for:
    - Per-user monthly cap enforcement (sum input/output tokens for current month).
    - Institutional billing reports.
    - Cost anomaly detection (alerts if daily spend > 2x trailing avg).
    """

    __tablename__ = "usage_events"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    session_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="SET NULL"),
        nullable=True,
    )

    model: Mapped[str] = mapped_column(String(100), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    cached_input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 6), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # For monthly cap queries: filter by user_id + created_at.
        Index("ix_usage_events_user_created", "user_id", "created_at"),
    )
