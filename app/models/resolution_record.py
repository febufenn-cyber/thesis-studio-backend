"""Reference-resolution cache — one row per resolved identifier or query.

Stores the merged, authority-sourced metadata for a DOI / arXiv id / ISBN /
free-text citation so re-runs and rate-limited batch imports never re-hit the
network. Nothing here overwrites a Source directly; ``apply_to_source`` decides
what (if anything) is written back under the never-guess discipline.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class ResolutionRecord(Base):
    """Cached resolution of one identifier or normalized free-text query."""

    __tablename__ = "resolution_records"
    __table_args__ = (
        UniqueConstraint(
            "identifier_kind", "identifier_value", name="uq_resolution_identifier"
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    # doi | arxiv | isbn | openalex | freetext
    identifier_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    # For free-text this is a normalized sha256 hex digest, not the raw string.
    identifier_value: Mapped[str] = mapped_column(String(300), nullable=False)
    # resolved | unresolved | ambiguous
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    # Merged normalized record: {registry_field: value}.
    canonical: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # Per-field provenance: {field: {authority, confidence, raw}}.
    provenance: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # Variant records seen across authorities (dedup audit).
    candidates: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # {retracted: bool, kind, notice_doi, source, checked_at} or null.
    retraction: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    authorities_tried: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    source_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    registry_kind: Mapped[str | None] = mapped_column(String(40), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
