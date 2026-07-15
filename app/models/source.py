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
    # Style-agnostic source type (article, book, conference_paper, standard,
    # patent, dataset, software, ...). Distinct from `kind`, which is the MLA
    # template key. Nullable for back-compat; populated as multi-style support
    # lands. See docs/DOMAIN_EXPANSION.md.
    source_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
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

    # Reference-enrichment provenance (docs/LLD.md 3.2). resolution_status:
    # None (never attempted) | resolved | unresolved | ambiguous. retraction_status:
    # None | none | retracted | concern. canonical_key collapses the same work
    # cited multiple ways; alternate_keys preserves the other identifiers seen.
    resolution_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    retraction_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    canonical_key: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    alternate_keys: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    # Optional stored source artifact used for quote verification (docs/LLD.md
    # 3.3). Mirrors the ManuscriptRevision storage columns.
    artifact_storage_key: Mapped[str | None] = mapped_column(String(700), nullable=True)
    artifact_mime_type: Mapped[str | None] = mapped_column(String(150), nullable=True)
    artifact_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
