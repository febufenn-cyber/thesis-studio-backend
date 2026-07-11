"""Phase 5 commercial reliability, security and scale control plane.

Revision ID: 0017
Revises: 0016
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.session import Base
import app.models  # noqa: F401 -- register all commercial tables on metadata


revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


_TABLES_IN_ORDER = [
    "product_editions", "edition_versions", "entitlement_definitions",
    "entitlement_grants", "usage_ledger", "cost_ledger", "billing_customers",
    "subscriptions", "subscription_items", "invoices", "payments", "billing_events",
    "tenant_budgets", "platform_budget_controls", "application_sessions",
    "ai_providers", "ai_provider_health", "feature_flags", "rollout_assignments",
    "release_records", "deployment_records", "service_components", "service_incidents",
    "slo_definitions", "sli_measurements", "recovery_policies", "backup_records",
    "restore_drills", "privacy_notice_versions", "consent_records", "processing_purposes",
    "data_inventory_records", "subprocessor_records", "security_requirement_evidence",
    "support_actions", "data_lifecycle_jobs",
]


def _create(name: str) -> None:
    Base.metadata.tables[name].create(op.get_bind(), checkfirst=True)


def _drop(name: str) -> None:
    Base.metadata.tables[name].drop(op.get_bind(), checkfirst=True)


def upgrade() -> None:
    for name in _TABLES_IN_ORDER:
        _create(name)

    op.add_column("jobs", sa.Column("queue_name", sa.String(40), nullable=False, server_default="general"))
    op.add_column("jobs", sa.Column("priority", sa.Integer(), nullable=False, server_default="100"))
    op.add_column("jobs", sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jobs", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jobs", sa.Column("idempotency_key", sa.String(180), nullable=True))
    op.add_column("jobs", sa.Column("release_sha", sa.String(64), nullable=True))
    op.add_column(
        "jobs",
        sa.Column("result", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.create_unique_constraint("uq_jobs_idempotency_key", "jobs", ["idempotency_key"])
    op.drop_index("ix_jobs_claim", table_name="jobs")
    op.create_index(
        "ix_jobs_claim", "jobs",
        ["queue_name", "status", "priority", "available_at", "created_at"],
    )
    op.create_index("ix_jobs_lease", "jobs", ["status", "lease_expires_at", "heartbeat_at"])

    op.add_column("ai_runs", sa.Column("provider_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("ai_runs", sa.Column("provider_slug", sa.String(80), nullable=True))
    op.add_column("ai_runs", sa.Column("provider_adapter", sa.String(50), nullable=True))
    op.add_column("ai_runs", sa.Column("queue_deadline_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        "fk_ai_runs_provider_id_ai_providers", "ai_runs", "ai_providers",
        ["provider_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_ai_runs_provider_status", "ai_runs", ["provider_id", "status", "created_at"])

    op.execute(
        """
        INSERT INTO entitlement_definitions
            (id, key, value_type, unit, description, customer_visible, metered, reset_period)
        VALUES
            (gen_random_uuid(), 'project.create', 'boolean', NULL, 'Create thesis projects.', true, false, NULL),
            (gen_random_uuid(), 'project.active_limit', 'integer', 'active_projects', 'Maximum active projects.', true, true, NULL),
            (gen_random_uuid(), 'manuscript.max_size_mb', 'integer', 'megabytes', 'Maximum manuscript upload size.', true, false, NULL),
            (gen_random_uuid(), 'ai.chat', 'boolean', NULL, 'Use grounded AI assistance.', true, false, NULL),
            (gen_random_uuid(), 'ai.chapter_review.monthly', 'integer', 'chapter_reviews', 'Deep chapter reviews per calendar month.', true, true, 'month'),
            (gen_random_uuid(), 'ai.whole_thesis_review.monthly', 'integer', 'whole_thesis_reviews', 'Whole-thesis reviews per calendar month.', true, true, 'month'),
            (gen_random_uuid(), 'export.docx', 'boolean', NULL, 'Generate verified DOCX exports.', true, false, NULL),
            (gen_random_uuid(), 'export.pdf', 'boolean', NULL, 'Generate verified PDF exports.', true, false, NULL),
            (gen_random_uuid(), 'export.pdf.monthly', 'integer', 'pdf_exports', 'Verified PDF exports per calendar month.', true, true, 'month'),
            (gen_random_uuid(), 'review.supervisor', 'boolean', NULL, 'Supervisor collaboration workflow.', true, false, NULL),
            (gen_random_uuid(), 'profile.custom', 'boolean', NULL, 'Create custom formatting profiles.', true, false, NULL),
            (gen_random_uuid(), 'seat.student_limit', 'integer', 'student_seats', 'Maximum active student seats.', true, true, NULL),
            (gen_random_uuid(), 'seat.staff_limit', 'integer', 'staff_seats', 'Maximum active staff seats.', true, true, NULL),
            (gen_random_uuid(), 'retention.days', 'integer', 'days', 'Default draft retention period.', true, false, NULL),
            (gen_random_uuid(), 'support.priority', 'string', NULL, 'Support service tier.', true, false, NULL)
        ON CONFLICT (key) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO product_editions (id, slug, audience, name, description, state)
        VALUES
            (gen_random_uuid(), 'student', 'student', 'Robofox Student', 'One governed thesis workspace for an individual student.', 'published'),
            (gen_random_uuid(), 'operator', 'operator', 'Robofox Operator', 'Multi-project professional formatting and client delivery.', 'published'),
            (gen_random_uuid(), 'institution', 'institution', 'Robofox Institution', 'Department and institution collaboration, governance and procurement.', 'published')
        ON CONFLICT (slug) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO service_components
            (id, key, name, description, public_status, state, metadata)
        VALUES
            (gen_random_uuid(), 'web', 'Web application', 'Application shell and project navigation.', true, 'operational', '{}'::jsonb),
            (gen_random_uuid(), 'auth', 'Authentication', 'OTP, identity and revocable sessions.', true, 'operational', '{}'::jsonb),
            (gen_random_uuid(), 'editing', 'Document editing', 'Canonical document reads and saves.', true, 'operational', '{}'::jsonb),
            (gen_random_uuid(), 'ai', 'AI assistance', 'Grounded AI queue and provider capacity.', true, 'operational', '{}'::jsonb),
            (gen_random_uuid(), 'ingestion', 'Manuscript ingestion', 'Upload preflight and deterministic parsing.', true, 'operational', '{}'::jsonb),
            (gen_random_uuid(), 'pdf', 'Preview and PDF generation', 'Dedicated rendering and conversion workers.', true, 'operational', '{}'::jsonb),
            (gen_random_uuid(), 'downloads', 'File downloads', 'Verified export and sealed-package downloads.', true, 'operational', '{}'::jsonb),
            (gen_random_uuid(), 'email', 'Email notifications', 'OTP and workflow notifications.', true, 'operational', '{}'::jsonb)
        ON CONFLICT (key) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("ix_ai_runs_provider_status", table_name="ai_runs")
    op.drop_constraint("fk_ai_runs_provider_id_ai_providers", "ai_runs", type_="foreignkey")
    op.drop_column("ai_runs", "queue_deadline_at")
    op.drop_column("ai_runs", "provider_adapter")
    op.drop_column("ai_runs", "provider_slug")
    op.drop_column("ai_runs", "provider_id")

    op.drop_index("ix_jobs_lease", table_name="jobs")
    op.drop_index("ix_jobs_claim", table_name="jobs")
    op.create_index("ix_jobs_claim", "jobs", ["status", "available_at", "created_at"])
    op.drop_constraint("uq_jobs_idempotency_key", "jobs", type_="unique")
    op.drop_column("jobs", "result")
    op.drop_column("jobs", "release_sha")
    op.drop_column("jobs", "idempotency_key")
    op.drop_column("jobs", "lease_expires_at")
    op.drop_column("jobs", "deadline_at")
    op.drop_column("jobs", "priority")
    op.drop_column("jobs", "queue_name")

    for name in reversed(_TABLES_IN_ORDER):
        _drop(name)
