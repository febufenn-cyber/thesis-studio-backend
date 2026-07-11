"""Institution workspace and tenant boundary."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class Institution(Base):
    """Institution tenant.

    A user's selected ``institution_id`` is only claimed affiliation. Verified
    authority is represented by ``OrganizationMembership``. Institution admins
    manage policy and operational metadata but do not automatically gain thesis
    content or private AI-history access.
    """

    __tablename__ = "institutions"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    short_name: Mapped[str] = mapped_column(String(50), nullable=False)
    slug: Mapped[str | None] = mapped_column(String(100), nullable=True, unique=True)
    email_domains: Mapped[str] = mapped_column(String(500), nullable=False)
    address: Mapped[str] = mapped_column(String(500), nullable=False)
    short_address: Mapped[str] = mapped_column(String(200), nullable=False)
    university_name: Mapped[str] = mapped_column(String(200), nullable=False)
    default_department: Mapped[str] = mapped_column(String(200), nullable=False)
    department_aided: Mapped[bool] = mapped_column(Boolean, default=False)
    logo_r2_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ai_disclosure_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    onboarding_state: Mapped[str] = mapped_column(String(32), nullable=False, default="setup_required")
    workspace_settings: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=lambda: {
            "admin_content_access_default": False,
            "email_content_previews": False,
            "support_access_requires_consent": True,
        },
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    @property
    def email_domains_list(self) -> list[str]:
        return [d.strip().lower() for d in self.email_domains.split(",") if d.strip()]
