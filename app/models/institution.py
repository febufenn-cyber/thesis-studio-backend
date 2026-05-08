"""Institution (college / university) model — multi-tenant support."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class Institution(Base):
    """An institution (college / university) using the platform.

    All institution-specific data lives here so it's entered once by an admin
    and reused across every student from that institution. Avoids typos in
    college names across hundreds of theses.

    Each user belongs to exactly one institution.
    """

    __tablename__ = "institutions"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)

    # Display name and identifiers
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    short_name: Mapped[str] = mapped_column(String(50), nullable=False)  # e.g. "MCC"

    # Email domain allowlist for this institution (comma-separated)
    email_domains: Mapped[str] = mapped_column(String(500), nullable=False)

    # Geography
    address: Mapped[str] = mapped_column(String(500), nullable=False)
    short_address: Mapped[str] = mapped_column(String(200), nullable=False)

    # Affiliated university (for the title page line)
    university_name: Mapped[str] = mapped_column(String(200), nullable=False)

    # Default values used for new sessions; students can override per session.
    default_department: Mapped[str] = mapped_column(String(200), nullable=False)
    department_aided: Mapped[bool] = mapped_column(Boolean, default=False)

    # Logo for the title page; stored as an R2 key, not the bytes themselves.
    logo_r2_key: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # AI-disclosure language (institution-specified) included in compiled docs.
    ai_disclosure_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Bookkeeping
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    @property
    def email_domains_list(self) -> list[str]:
        """Parsed list of allowed email domains for this institution."""
        return [d.strip().lower() for d in self.email_domains.split(",") if d.strip()]
