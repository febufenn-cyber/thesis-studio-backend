"""Phase 1 trusted conversion: revisions, jobs, provenance and versioned exports.

Revision ID: 0007
Revises: 0006
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("active_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "projects",
        sa.Column("document_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.alter_column("projects", "format_profile", type_=sa.String(80))

    op.create_table(
        "manuscript_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("supersedes_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("original_filename", sa.String(300), nullable=False),
        sa.Column("storage_key", sa.String(700), nullable=False),
        sa.Column("mime_type", sa.String(150), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("parser_version", sa.String(50), nullable=False),
        sa.Column("canonical_schema_version", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("canonical_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("import_report", postgresql.JSONB(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="queued"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("applied", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["supersedes_revision_id"], ["manuscript_revisions.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint("project_id", "revision_number", name="uq_manuscript_revision_number"),
    )
    op.create_index("ix_manuscript_revisions_project_id", "manuscript_revisions", ["project_id"])
    op.create_index("ix_manuscript_revisions_user_id", "manuscript_revisions", ["user_id"])
    op.create_index(
        "ix_manuscript_revision_checksum", "manuscript_revisions", ["project_id", "checksum"]
    )

    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(120), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_jobs_project_id", "jobs", ["project_id"])
    op.create_index("ix_jobs_user_id", "jobs", ["user_id"])
    op.create_index("ix_jobs_claim", "jobs", ["status", "available_at", "created_at"])
    op.create_index("ix_jobs_project_kind", "jobs", ["project_id", "kind", "status"])

    op.add_column("sources", sa.Column("raw_entry", sa.Text(), nullable=True))
    op.add_column(
        "sources",
        sa.Column("parse_status", sa.String(30), nullable=False, server_default="structured_with_review"),
    )
    op.add_column("sources", sa.Column("source_paragraph_index", sa.Integer(), nullable=True))
    op.add_column(
        "sources", sa.Column("import_revision_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.add_column("sources", sa.Column("parser_confidence", sa.Float(), nullable=True))
    op.add_column("sources", sa.Column("parser_version", sa.String(50), nullable=True))
    op.add_column(
        "sources",
        sa.Column("identifiers", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.add_column("sources", sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("sources", sa.Column("verified_by", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("sources", sa.Column("verification_method", sa.String(40), nullable=True))
    op.create_foreign_key(
        "fk_sources_import_revision", "sources", "manuscript_revisions", ["import_revision_id"], ["id"], ondelete="SET NULL"
    )
    op.create_foreign_key(
        "fk_sources_verified_by", "sources", "users", ["verified_by"], ["id"], ondelete="SET NULL"
    )
    op.create_index("ix_sources_import_revision_id", "sources", ["import_revision_id"])

    op.add_column("quotes", sa.Column("import_revision_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("quotes", sa.Column("source_paragraph_index", sa.Integer(), nullable=True))
    op.add_column(
        "quotes",
        sa.Column("evidence_snapshot", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.add_column("quotes", sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("quotes", sa.Column("verified_by", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("quotes", sa.Column("verification_method", sa.String(40), nullable=True))
    op.alter_column("quotes", "page_or_loc", type_=sa.String(100))
    op.alter_column("quotes", "method", type_=sa.String(30))
    op.create_foreign_key(
        "fk_quotes_import_revision", "quotes", "manuscript_revisions", ["import_revision_id"], ["id"], ondelete="SET NULL"
    )
    op.create_foreign_key(
        "fk_quotes_verified_by", "quotes", "users", ["verified_by"], ["id"], ondelete="SET NULL"
    )
    op.create_index("ix_quotes_import_revision_id", "quotes", ["import_revision_id"])

    op.add_column("exports", sa.Column("document_version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("exports", sa.Column("manuscript_revision_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column(
        "exports", sa.Column("profile_version", sa.String(120), nullable=False, server_default="builtin")
    )
    op.add_column("exports", sa.Column("manifest", postgresql.JSONB(), nullable=True))
    op.create_foreign_key(
        "fk_exports_manuscript_revision", "exports", "manuscript_revisions", ["manuscript_revision_id"], ["id"], ondelete="SET NULL"
    )
    op.drop_index("uq_exports_project_format_running", table_name="exports")
    op.create_index(
        "uq_exports_project_format_running",
        "exports",
        ["project_id", "format"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )


def downgrade() -> None:
    op.drop_index("uq_exports_project_format_running", table_name="exports")
    op.create_index(
        "uq_exports_project_format_running",
        "exports",
        ["project_id", "format"],
        unique=True,
        postgresql_where=sa.text("status = 'running'"),
    )
    op.drop_constraint("fk_exports_manuscript_revision", "exports", type_="foreignkey")
    op.drop_column("exports", "manifest")
    op.drop_column("exports", "profile_version")
    op.drop_column("exports", "manuscript_revision_id")
    op.drop_column("exports", "document_version")

    op.drop_index("ix_quotes_import_revision_id", table_name="quotes")
    op.drop_constraint("fk_quotes_verified_by", "quotes", type_="foreignkey")
    op.drop_constraint("fk_quotes_import_revision", "quotes", type_="foreignkey")
    for column in (
        "verification_method", "verified_by", "verified_at", "evidence_snapshot",
        "source_paragraph_index", "import_revision_id",
    ):
        op.drop_column("quotes", column)
    op.alter_column("quotes", "page_or_loc", type_=sa.String(50))
    op.alter_column("quotes", "method", type_=sa.String(20))

    op.drop_index("ix_sources_import_revision_id", table_name="sources")
    op.drop_constraint("fk_sources_verified_by", "sources", type_="foreignkey")
    op.drop_constraint("fk_sources_import_revision", "sources", type_="foreignkey")
    for column in (
        "verification_method", "verified_by", "verified_at", "identifiers",
        "parser_version", "parser_confidence", "import_revision_id",
        "source_paragraph_index", "parse_status", "raw_entry",
    ):
        op.drop_column("sources", column)

    op.drop_table("jobs")
    op.drop_table("manuscript_revisions")
    op.drop_column("projects", "document_version")
    op.drop_column("projects", "active_revision_id")
    op.alter_column("projects", "format_profile", type_=sa.String(30))
