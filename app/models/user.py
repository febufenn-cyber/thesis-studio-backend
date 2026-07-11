"""User identity model; institutional privilege lives in explicit memberships."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class User(Base):
    """Authenticated identity.

    ``institution_id`` is retained as the selected/legacy home institution for
    compatibility. It is not proof of institutional authority. Phase 4 grants
    privileges only through verified organization/project memberships.
    """

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    full_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    register_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    identity_provider: Mapped[str] = mapped_column(String(30), nullable=False, default="email_otp")
    account_status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    affiliation_status: Mapped[str] = mapped_column(String(32), nullable=False, default="affiliation_claimed")

    institution_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("institutions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    institution = relationship("Institution", lazy="joined")
