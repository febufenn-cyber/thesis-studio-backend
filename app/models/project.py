"""Project model — one v2 thesis project per row.

M1 deviation: chapters, front_matter, and works_cited are stored as JSONB
directly on the project row (rather than per-chapter rows) to keep M1/M2
simple.  Per-chapter rows with Mode A gates arrive in M5.  See DESIGN.md §4.1
for the full intended schema.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class Project(Base):
    """A v2 formatting/research project belonging to one user.

    ``mode`` is ``"student"`` (Mode A — guided coaching flow) or
    ``"operator"`` (Mode B — formatting service bureau).
    ``status`` tracks the project lifecycle: ``"formatting"`` → ``"drafting"``
    → ``"reviewing"`` → ``"done"``.
    ``format_profile`` names the built-in FORMAT_SPEC profile (``tn_university``
    or ``mla_strict``) used when ``style_profile_id`` is None.
    ``meta``, ``front_matter``, ``chapters``, and ``works_cited`` hold the
    serialised ThesisDocument sub-objects (see app.canonical.model).
    """

    __tablename__ = "projects"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="operator")
    doc_type: Mapped[str] = mapped_column(String(30), nullable=False, default="ma_dissertation")
    title: Mapped[str] = mapped_column(String(300), nullable=False, default="Untitled Project")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="formatting")
    format_profile: Mapped[str] = mapped_column(String(30), nullable=False, default="tn_university")

    # FK to a user-created StyleProfile; null means use the built-in profile.
    style_profile_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("style_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ThesisMeta serialised as JSONB.  Default {} lets ThesisMeta.model_validate({})
    # succeed (all sub-models have defaults).
    meta: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # list[FrontMatterEntry] serialised as JSONB.
    front_matter: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    # list[ChapterDoc] serialised as JSONB.
    chapters: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    # list[WorksCitedRef] serialised as JSONB.
    works_cited: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
