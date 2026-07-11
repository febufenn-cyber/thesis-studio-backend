"""Project model — one canonical thesis project per row."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


_DEFAULT_AI_POLICY = {
    "allowed_modes": ["understand", "diagnose", "plan", "transform", "challenge", "research", "coherence", "viva"],
    "external_research": False,
    "private_threads": True,
    "supervisor_constraints": [],
    "disclosure_required": True,
}


class Project(Base):
    """Canonical thesis plus its governed institutional workflow.

    ``user_id`` remains the visible student-author/legacy owner. Shared access is
    never inferred from this field: Phase 4 uses verified organization and
    project memberships with explicit capabilities. ``document_version`` is
    incremented for every canonical mutation and review/approval records bind to
    immutable snapshots of a precise version.
    """

    __tablename__ = "projects"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    institution_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("institutions.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    department_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("departments.id", ondelete="SET NULL"), nullable=True, index=True
    )

    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="operator")
    doc_type: Mapped[str] = mapped_column(String(30), nullable=False, default="ma_dissertation")
    title: Mapped[str] = mapped_column(String(300), nullable=False, default="Untitled Project")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="formatting")
    workflow_state: Mapped[str] = mapped_column(String(40), nullable=False, default="draft")
    format_profile: Mapped[str] = mapped_column(String(80), nullable=False, default="tn_university")

    style_profile_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("style_profiles.id", ondelete="SET NULL"), nullable=True
    )
    institutional_profile_version_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey(
            "institutional_profile_versions.id",
            name="fk_projects_institutional_profile_version",
            ondelete="SET NULL",
            use_alter=True,
        ),
        nullable=True,
    )
    institutional_policy_version_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey(
            "institutional_policy_versions.id",
            name="fk_projects_institutional_policy_version",
            ondelete="SET NULL",
            use_alter=True,
        ),
        nullable=True,
    )
    active_revision_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey(
            "manuscript_revisions.id",
            name="fk_projects_active_revision",
            ondelete="SET NULL",
            use_alter=True,
        ),
        nullable=True,
    )
    document_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    canonical_schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=3)

    meta: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    front_matter: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    chapters: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    works_cited: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    ai_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    ai_policy: Mapped[dict] = mapped_column(JSONB, nullable=False, default=lambda: dict(_DEFAULT_AI_POLICY))
    collaboration_policy: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=lambda: {
            "student_owns_acceptance": True,
            "supervisor_ai_history_default": False,
            "admin_content_access_default": False,
            "operator_prose_edit": False,
            "external_review": True,
        },
    )
    submission_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
