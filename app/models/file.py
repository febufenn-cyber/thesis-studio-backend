"""Generated file model — Word docs / PDFs produced by the compile pipeline."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


# File type values
FILE_TYPE_DOCX = "docx"
FILE_TYPE_PDF = "pdf"


class File(Base):
    """A generated file (compiled thesis docx or pdf) stored in R2.

    Note `user_id` is denormalized here — it could be derived via session.user_id,
    but storing it directly makes auth checks one query instead of a join, and
    survives session deletion if we ever soft-delete sessions.
    """

    __tablename__ = "files"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)

    session_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    filename: Mapped[str] = mapped_column(String(300), nullable=False)
    file_type: Mapped[str] = mapped_column(String(20), nullable=False)  # 'docx' | 'pdf'
    r2_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="ready"
    )  # 'compiling' | 'ready' | 'failed'
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_files_session_created", "session_id", "created_at"),
        # At most one in-flight compile per session. Closes the TOCTOU window
        # in the route-level 409 guard: a racing second INSERT raises
        # IntegrityError, which the global handler maps to 409.
        Index(
            "uq_files_session_compiling",
            "session_id",
            unique=True,
            postgresql_where=text("status = 'compiling'"),
        ),
    )
