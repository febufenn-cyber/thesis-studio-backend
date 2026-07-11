"""Phase 4 collaborative academic workspace.

Revision ID: 0012
Revises: 0011
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.session import Base
import app.models  # noqa: F401 -- registers Phase 4 tables on Base metadata


revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


_TABLES_IN_ORDER = [
    "departments",
    "organization_memberships",
    "project_memberships",
    "membership_invitations",
    "review_assignments",
    "project_handoffs",
    "notifications",
    "notification_preferences",
    "data_lifecycle_requests",
    "support_access_grants",
    "institutional_policy_versions",
    "institutional_profile_versions",
    "official_template_versions",
    "retention_policies",
    "submission_packages",
    "review_cycles",
    "collaboration_comments",
    "human_suggestions",
    "approval_records",
    "supervisor_instructions",
    "attestations",
    "external_review_grants",
]


def _create_table(name: str) -> None:
    Base.metadata.tables[name].create(op.get_bind(), checkfirst=True)


def _drop_table(name: str) -> None:
    Base.metadata.tables[name].drop(op.get_bind(), checkfirst=True)


def upgrade() -> None:
    # Identity and institution workspace state. Existing verified email users keep
    # access to their own projects, but no new administrator privileges are inferred.
    op.add_column("users", sa.Column("identity_provider", sa.String(30), nullable=False, server_default="email_otp"))
    op.add_column("users", sa.Column("account_status", sa.String(24), nullable=False, server_default="active"))
    op.add_column("users", sa.Column("affiliation_status", sa.String(32), nullable=False, server_default="domain_verified"))

    op.add_column("institutions", sa.Column("slug", sa.String(100), nullable=True))
    op.create_unique_constraint("uq_institutions_slug", "institutions", ["slug"])
    op.add_column("institutions", sa.Column("onboarding_state", sa.String(32), nullable=False, server_default="setup_required"))
    op.add_column(
        "institutions",
        sa.Column(
            "workspace_settings",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text(
                "'{\"admin_content_access_default\":false,\"email_content_previews\":false,\"support_access_requires_consent\":true}'::jsonb"
            ),
        ),
    )

    # Tables that the project governance foreign keys depend on.
    for name in _TABLES_IN_ORDER[:14]:
        _create_table(name)

    op.add_column("projects", sa.Column("institution_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("projects", sa.Column("department_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("projects", sa.Column("workflow_state", sa.String(40), nullable=False, server_default="student_review"))
    op.add_column("projects", sa.Column("institutional_profile_version_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("projects", sa.Column("institutional_policy_version_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column(
        "projects",
        sa.Column(
            "collaboration_policy",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text(
                "'{\"student_owns_acceptance\":true,\"supervisor_ai_history_default\":false,\"admin_content_access_default\":false,\"operator_prose_edit\":false,\"external_review\":true}'::jsonb"
            ),
        ),
    )
    op.add_column("projects", sa.Column("submission_locked", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute(
        "UPDATE projects p SET institution_id = u.institution_id FROM users u WHERE p.user_id = u.id AND p.institution_id IS NULL"
    )
    op.create_foreign_key("fk_projects_institution_id", "projects", "institutions", ["institution_id"], ["id"], ondelete="RESTRICT")
    op.create_foreign_key("fk_projects_department_id", "projects", "departments", ["department_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key(
        "fk_projects_institutional_profile_version",
        "projects",
        "institutional_profile_versions",
        ["institutional_profile_version_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_projects_institutional_policy_version",
        "projects",
        "institutional_policy_versions",
        ["institutional_policy_version_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_projects_institution_id", "projects", ["institution_id"])
    op.create_index("ix_projects_department_id", "projects", ["department_id"])

    # Remaining tables depend on the newly added project governance columns or on
    # each other (submission packages before attestations/external grants).
    for name in _TABLES_IN_ORDER[14:]:
        _create_table(name)


def downgrade() -> None:
    for name in reversed(_TABLES_IN_ORDER[14:]):
        _drop_table(name)

    op.drop_index("ix_projects_department_id", table_name="projects")
    op.drop_index("ix_projects_institution_id", table_name="projects")
    op.drop_constraint("fk_projects_institutional_policy_version", "projects", type_="foreignkey")
    op.drop_constraint("fk_projects_institutional_profile_version", "projects", type_="foreignkey")
    op.drop_constraint("fk_projects_department_id", "projects", type_="foreignkey")
    op.drop_constraint("fk_projects_institution_id", "projects", type_="foreignkey")
    op.drop_column("projects", "submission_locked")
    op.drop_column("projects", "collaboration_policy")
    op.drop_column("projects", "institutional_policy_version_id")
    op.drop_column("projects", "institutional_profile_version_id")
    op.drop_column("projects", "workflow_state")
    op.drop_column("projects", "department_id")
    op.drop_column("projects", "institution_id")

    for name in reversed(_TABLES_IN_ORDER[:14]):
        _drop_table(name)

    op.drop_column("institutions", "workspace_settings")
    op.drop_column("institutions", "onboarding_state")
    op.drop_constraint("uq_institutions_slug", "institutions", type_="unique")
    op.drop_column("institutions", "slug")
    op.drop_column("users", "affiliation_status")
    op.drop_column("users", "account_status")
    op.drop_column("users", "identity_provider")
