"""Versioned institutional policy/profile/template and sealed-submission models."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class InstitutionalPolicyVersion(Base):
    __tablename__ = "institutional_policy_versions"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    institution_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("institutions.id", ondelete="CASCADE"), nullable=False
    )
    department_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("departments.id", ondelete="CASCADE"), nullable=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    policy: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    published_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deprecated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("institution_id", "department_id", "version", name="uq_policy_scope_version"),
        Index("ix_policy_scope_state", "institution_id", "department_id", "state"),
    )


class InstitutionalProfileVersion(Base):
    __tablename__ = "institutional_profile_versions"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    institution_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("institutions.id", ondelete="CASCADE"), nullable=False
    )
    department_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("departments.id", ondelete="CASCADE"), nullable=True
    )
    programme: Mapped[str] = mapped_column(String(160), nullable=False)
    academic_year: Mapped[str] = mapped_column(String(40), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    base_profile: Mapped[str] = mapped_column(String(100), nullable=False, default="tn_university")
    profile_data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    required_front_matter: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    locked_template_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    impact_summary: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    published_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deprecated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "institution_id", "department_id", "programme", "academic_year", "version",
            name="uq_profile_scope_programme_version",
        ),
        Index("ix_profile_scope_state", "institution_id", "department_id", "state"),
    )


class OfficialTemplateVersion(Base):
    __tablename__ = "official_template_versions"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    institution_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("institutions.id", ondelete="CASCADE"), nullable=False
    )
    department_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("departments.id", ondelete="CASCADE"), nullable=True
    )
    template_kind: Mapped[str] = mapped_column(String(60), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    body: Mapped[str] = mapped_column(Text, nullable=False)
    structured: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    academic_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deprecated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "institution_id", "department_id", "template_kind", "version",
            name="uq_official_template_scope_kind_version",
        ),
        Index("ix_official_template_scope_state", "institution_id", "department_id", "state"),
    )


class RetentionPolicy(Base):
    __tablename__ = "retention_policies"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    institution_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("institutions.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    policy: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    published_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (UniqueConstraint("institution_id", "version", name="uq_retention_policy_version"),)


class SubmissionPackage(Base):
    __tablename__ = "submission_packages"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    institution_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("institutions.id", ondelete="RESTRICT"), nullable=False
    )
    department_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("departments.id", ondelete="SET NULL"), nullable=True
    )
    package_number: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="sealed")
    snapshot_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("document_snapshots.id", ondelete="RESTRICT"), nullable=False
    )
    document_version: Mapped[int] = mapped_column(Integer, nullable=False)
    document_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    profile_version_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("institutional_profile_versions.id", ondelete="RESTRICT"), nullable=True
    )
    policy_version_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("institutional_policy_versions.id", ondelete="RESTRICT"), nullable=True
    )
    export_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    approval_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    manifest: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    package_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    sealed_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    sealed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    withdrawn_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    withdrawal_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    superseded_by_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("submission_packages.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("project_id", "package_number", name="uq_submission_package_number"),
        Index("ix_submission_package_project_state", "project_id", "state"),
    )


class ExternalReviewGrant(Base):
    __tablename__ = "external_review_grants"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    submission_package_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("submission_packages.id", ondelete="CASCADE"), nullable=False
    )
    recipient_email: Mapped[str] = mapped_column(String(255), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    permissions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    watermark: Mapped[str | None] = mapped_column(String(300), nullable=True)
    download_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    revoked_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    access_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_external_review_package_status", "submission_package_id", "status", "expires_at"),
    )
