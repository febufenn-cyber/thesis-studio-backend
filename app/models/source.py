"""Source model — Citation Registry entry for a project."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class Source(Base):
    """One entry in the Citation Registry for a project.

    ``kind`` is one of: ``book``, ``translated_book``, ``chapter_in_collection``,
    ``journal``, ``journal_db``, ``web``, ``film`` (FORMAT_SPEC §6).
    ``fields`` holds the kind-specific bibliographic fields as JSONB.
    ``verified`` is set by CITATION_VERIFIER or manual review; ``verify_note``
    explains unverifiable entries.
    ``consulted_flag`` marks sources cited as "Works Consulted" but not directly
    quoted in the body.
    """

    __tablename__ = "sources"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)

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

    kind: Mapped[str] = mapped_column(String(30), nullable=False)

    # Kind-specific bibliographic fields (author, title, publisher, year, etc.)
    # per FORMAT_SPEC §6 templates.
    fields: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    verify_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Marks sources that were consulted but not directly cited (Works Consulted).
    consulted_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
