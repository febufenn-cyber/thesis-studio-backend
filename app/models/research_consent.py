"""Research-donation consent (docs/LLD.md 3.8).

Opt-in, revocable, version-pinned. Revocation sets ``revoked_at`` (never a
delete), and a partial unique index enforces at most one *live* grant per
(user, scope) while allowing re-grant after revocation.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class ResearchConsent(Base):
    __tablename__ = "research_consents"
    __table_args__ = (
        Index("ix_research_consent_active", "user_id", "scope", "revoked_at"),
        Index(
            "uq_research_consent_live",
            "user_id",
            "scope",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # revision_history | citation_patterns | ai_provenance | all
    scope: Mapped[str] = mapped_column(String(40), nullable=False)
    terms_version: Mapped[str] = mapped_column(String(20), nullable=False)
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    granted_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    revoked_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
