"""Phase 2 human review and editing workspace.

Revision ID: 0009
Revises: 0008
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("canonical_schema_version", sa.Integer(), nullable=False, server_default="3"),
    )

    op.create_table(
        "document_commands",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("command_type", sa.String(60), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("inverse_payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("summary", sa.String(400), nullable=False, server_default=""),
        sa.Column("target_type", sa.String(30), nullable=True),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("client_request_id", sa.String(120), nullable=True),
        sa.Column("document_version_before", sa.Integer(), nullable=False),
        sa.Column("document_version_after", sa.Integer(), nullable=False),
        sa.Column("replays_command_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("project_id", "client_request_id", name="uq_document_command_client_request"),
    )
    op.create_index("ix_document_commands_project_id", "document_commands", ["project_id"])
    op.create_index("ix_document_commands_user_id", "document_commands", ["user_id"])
    op.create_index("ix_document_commands_target_id", "document_commands", ["target_id"])
    op.create_index("ix_document_commands_batch_id", "document_commands", ["batch_id"])
    op.create_index("ix_document_commands_created_at", "document_commands", ["created_at"])

    op.create_table(
        "document_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("manuscript_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("reason", sa.String(60), nullable=False, server_default="manual"),
        sa.Column("automatic", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("document_version", sa.Integer(), nullable=False),
        sa.Column("canonical_document", postgresql.JSONB(), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["manuscript_revision_id"], ["manuscript_revisions.id"], ondelete="SET NULL"
        ),
    )
    op.create_index("ix_document_snapshots_project_id", "document_snapshots", ["project_id"])
    op.create_index("ix_document_snapshots_user_id", "document_snapshots", ["user_id"])
    op.create_index(
        "ix_document_snapshots_manuscript_revision_id",
        "document_snapshots",
        ["manuscript_revision_id"],
    )
    op.create_index("ix_document_snapshots_document_version", "document_snapshots", ["document_version"])
    op.create_index("ix_document_snapshots_created_at", "document_snapshots", ["created_at"])

    op.create_table(
        "review_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("block_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("quote_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("rule", sa.String(100), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False, server_default=""),
        sa.Column("why_it_matters", sa.Text(), nullable=False, server_default=""),
        sa.Column("location", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("recommended_actions", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("evidence", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(24), nullable=False, server_default="open"),
        sa.Column("first_seen_version", sa.Integer(), nullable=False),
        sa.Column("last_seen_version", sa.Integer(), nullable=False),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("resolution_history", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("resolved_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["revision_id"], ["manuscript_revisions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["quote_id"], ["quotes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["resolved_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("project_id", "fingerprint", name="uq_review_item_fingerprint"),
    )
    for name, columns in (
        ("ix_review_items_project_id", ["project_id"]),
        ("ix_review_items_user_id", ["user_id"]),
        ("ix_review_items_revision_id", ["revision_id"]),
        ("ix_review_items_block_id", ["block_id"]),
        ("ix_review_items_category", ["category"]),
        ("ix_review_items_rule", ["rule"]),
        ("ix_review_items_severity", ["severity"]),
        ("ix_review_items_status", ["status"]),
    ):
        op.create_index(name, "review_items", columns)

    op.create_table(
        "document_previews",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("manuscript_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("document_version", sa.Integer(), nullable=False),
        sa.Column("profile_version", sa.String(160), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="queued"),
        sa.Column("storage_key", sa.String(700), nullable=True),
        sa.Column("checksum", sa.String(64), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("manifest", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["manuscript_revision_id"], ["manuscript_revisions.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint(
            "project_id",
            "document_version",
            "profile_version",
            name="uq_document_preview_version_profile",
        ),
    )
    op.create_index("ix_document_previews_project_id", "document_previews", ["project_id"])
    op.create_index("ix_document_previews_user_id", "document_previews", ["user_id"])
    op.create_index(
        "ix_document_previews_manuscript_revision_id",
        "document_previews",
        ["manuscript_revision_id"],
    )
    op.create_index("ix_document_previews_document_version", "document_previews", ["document_version"])
    op.create_index("ix_document_previews_status", "document_previews", ["status"])


def downgrade() -> None:
    op.drop_table("document_previews")
    op.drop_table("review_items")
    op.drop_table("document_snapshots")
    op.drop_table("document_commands")
    op.drop_column("projects", "canonical_schema_version")
