"""Phase 3 grounded AI thesis partner.

Revision ID: 0010
Revises: 0009
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


# The richer application default lives in Project. A neutral JSONB default is
# used here because SQLAlchemy text() treats JSON ``:false``/``:true`` tokens as
# bind parameters inside a DDL default. Runtime policy reads apply safe fallbacks.
_DEFAULT_POLICY = sa.text("'{}'::jsonb")


def upgrade() -> None:
    op.add_column(
        "projects", sa.Column("ai_enabled", sa.Boolean(), nullable=False, server_default=sa.true())
    )
    op.add_column(
        "projects", sa.Column("ai_policy", postgresql.JSONB(), nullable=False, server_default=_DEFAULT_POLICY)
    )
    op.add_column("sessions", sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_sessions_project_id", "sessions", "projects", ["project_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index("ix_sessions_project_id", "sessions", ["project_id"])

    op.create_table(
        "ai_threads",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("legacy_session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(240), nullable=False, server_default="Robofox Scholar"),
        sa.Column("scope", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("private", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["legacy_session_id"], ["sessions.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_ai_threads_project_updated", "ai_threads", ["project_id", "updated_at"])
    op.create_index("ix_ai_threads_user_id", "ai_threads", ["user_id"])
    op.create_index("ix_ai_threads_legacy_session_id", "ai_threads", ["legacy_session_id"])

    op.create_table(
        "ai_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("task_mode", sa.String(40), nullable=True),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("structured", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("scope", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("document_version", sa.Integer(), nullable=False),
        sa.Column("model", sa.String(120), nullable=True),
        sa.Column("prompt_name", sa.String(100), nullable=True),
        sa.Column("prompt_version", sa.String(40), nullable=True),
        sa.Column("context_manifest", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("usage", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["thread_id"], ["ai_threads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_ai_messages_thread_created", "ai_messages", ["thread_id", "created_at"])
    op.create_index("ix_ai_messages_project_id", "ai_messages", ["project_id"])
    op.create_index("ix_ai_messages_user_id", "ai_messages", ["user_id"])

    op.create_table(
        "ai_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("task_mode", sa.String(40), nullable=False),
        sa.Column("result_type", sa.String(30), nullable=False, server_default="conversation"),
        sa.Column("risk_level", sa.String(20), nullable=False, server_default="low"),
        sa.Column("scope", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(24), nullable=False, server_default="queued"),
        sa.Column("requested_document_version", sa.Integer(), nullable=False),
        sa.Column("prompt_name", sa.String(100), nullable=False),
        sa.Column("prompt_version", sa.String(40), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("context_manifest", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("context_hash", sa.String(64), nullable=True),
        sa.Column("progress", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["thread_id"], ["ai_threads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["request_message_id"], ["ai_messages.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_ai_runs_project_status", "ai_runs", ["project_id", "status"])
    op.create_index("ix_ai_runs_thread_created", "ai_runs", ["thread_id", "created_at"])
    op.create_index("ix_ai_runs_user_status", "ai_runs", ["user_id", "status"])

    op.create_table(
        "ai_proposals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("based_on_document_version", sa.Integer(), nullable=False),
        sa.Column("task_mode", sa.String(40), nullable=False),
        sa.Column("risk_level", sa.String(20), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="open"),
        sa.Column("scope", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("rationale", sa.Text(), nullable=False, server_default=""),
        sa.Column("explanation", sa.Text(), nullable=False, server_default=""),
        sa.Column("operations", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("evidence", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("assumptions", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("unresolved_requirements", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("prompt_name", sa.String(100), nullable=False),
        sa.Column("prompt_version", sa.String(40), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("context_manifest", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("context_hash", sa.String(64), nullable=False),
        sa.Column("selected_operation_indexes", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("rejection_reason", sa.String(80), nullable=True),
        sa.Column("decision_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_command_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("verifier_before", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("verifier_after", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["run_id"], ["ai_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["thread_id"], ["ai_threads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["decision_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["applied_command_id"], ["document_commands.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("run_id", name="uq_ai_proposal_run"),
    )
    op.create_index("ix_ai_proposals_project_status", "ai_proposals", ["project_id", "status"])
    op.create_index("ix_ai_proposals_thread_created", "ai_proposals", ["thread_id", "created_at"])
    op.create_index("ix_ai_proposals_user_id", "ai_proposals", ["user_id"])

    op.create_table(
        "ai_memories",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope_type", sa.String(30), nullable=False),
        sa.Column("scope_key", sa.String(100), nullable=False, server_default="project"),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("content", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("based_on_document_version", sa.Integer(), nullable=False),
        sa.Column("generated_by", sa.String(20), nullable=False, server_default="ai"),
        sa.Column("prompt_version", sa.String(40), nullable=True),
        sa.Column("model", sa.String(120), nullable=True),
        sa.Column("stale", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("project_id", "scope_type", "scope_key", "kind", name="uq_ai_memory_scope_kind"),
    )
    op.create_index("ix_ai_memories_project_stale", "ai_memories", ["project_id", "stale"])
    op.create_index("ix_ai_memories_user_id", "ai_memories", ["user_id"])

    op.create_table(
        "research_candidates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("query", sa.Text(), nullable=False, server_default=""),
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column("authors", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("year", sa.String(20), nullable=True),
        sa.Column("source_type", sa.String(40), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("doi", sa.String(300), nullable=True),
        sa.Column("snippet", sa.Text(), nullable=True),
        sa.Column("metadata_payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(32), nullable=False, server_default="candidate"),
        sa.Column("added_source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["thread_id"], ["ai_threads.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["added_source_id"], ["sources.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_research_candidates_project_status", "research_candidates", ["project_id", "status"])
    op.create_index("ix_research_candidates_user_id", "research_candidates", ["user_id"])
    op.create_index("ix_research_candidates_thread_id", "research_candidates", ["thread_id"])


def downgrade() -> None:
    op.drop_table("research_candidates")
    op.drop_table("ai_memories")
    op.drop_table("ai_proposals")
    op.drop_table("ai_runs")
    op.drop_table("ai_messages")
    op.drop_table("ai_threads")
    op.drop_index("ix_sessions_project_id", table_name="sessions")
    op.drop_constraint("fk_sessions_project_id", "sessions", type_="foreignkey")
    op.drop_column("sessions", "project_id")
    op.drop_column("projects", "ai_policy")
    op.drop_column("projects", "ai_enabled")
