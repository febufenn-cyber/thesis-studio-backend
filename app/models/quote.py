"""Quote model — a verified or pasted quotation linked to a registry source."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class Quote(Base):
    """One quotation entry in the Citation Registry.

    Quotes enter via three paths (DESIGN.md §7):
    (a) student pastes passage + page (method=``"pasted"``),
    (b) extraction from an ingested text (method=``"extracted"``),
    (c) web retrieval (method=``"web_retrieved"``).
    DRAFT_PARTNER may only place quotes that have a corresponding Quote row;
    anything missing becomes a ``QUOTE_NEEDED`` MarkerBlock.
    """

    __tablename__ = "quotes"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)

    source_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    page_or_loc: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    text: Mapped[str] = mapped_column(Text, nullable=False)

    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # How the quotation was obtained: pasted | extracted | web_retrieved
    method: Mapped[str] = mapped_column(String(20), nullable=False, default="pasted")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
