"""StyleProfile model — persists a FORMAT_SPEC §8 profile JSON for a user."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class StyleProfile(Base):
    """A named formatting profile derived from an exemplar thesis (§8).

    ``base`` names the built-in profile being overridden (e.g. ``tn_university``
    or ``mla_strict``).  ``data`` holds the full StyleProfile JSON as a JSONB
    column; renderers call ``profiles.resolve_profile(base, data)`` to merge
    it with the base defaults.
    """

    __tablename__ = "style_profiles"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    base: Mapped[str] = mapped_column(String(30), nullable=False, default="tn_university")

    # Full FORMAT_SPEC §8 JSON blob.
    data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
