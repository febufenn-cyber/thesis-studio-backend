"""Export model — a rendered output file (docx/pdf/md/txt) for a project."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class Export(Base):
    """One export job for a project in a specific format.

    ``status`` lifecycle: ``"running"`` → ``"ready"`` | ``"failed"``.
    ``storage_key`` is the R2 object key (or local path in dev) written by
    the render worker.
    ``checksum`` is the SHA-256 hex digest of the rendered file.
    ``report`` holds the FORMAT_QA violation list (see FORMAT_SPEC §9):
    ``{"pass": bool, "violations": [...]}``.

    The partial unique index ``uq_exports_project_format_running`` prevents
    two simultaneous render jobs for the same (project, format) pair — a
    racing second INSERT raises IntegrityError (mapped to 409 by the global
    handler).
    """

    __tablename__ = "exports"

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

    format: Mapped[str] = mapped_column(String(10), nullable=False)  # docx | pdf | md | txt

    storage_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="running"
    )  # running | ready | failed
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # FORMAT_QA report: {"pass": bool, "violations": [...]}
    report: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # Prevents two simultaneous render jobs for the same (project, format).
        Index(
            "uq_exports_project_format_running",
            "project_id",
            "format",
            unique=True,
            postgresql_where=text("status = 'running'"),
        ),
    )
