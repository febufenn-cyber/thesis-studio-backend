"""v2 project tables: style_profiles, projects, sources, quotes, exports, events.

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-10

All six tables are new; no existing v1 tables are altered.  Downgrade drops
them in FK-safe reverse order.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # style_profiles — no FK deps other than users
    # ------------------------------------------------------------------
    op.create_table(
        "style_profiles",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("base", sa.String(30), nullable=False, server_default="tn_university"),
        sa.Column("data", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_style_profiles_user_id", "style_profiles", ["user_id"])

    # ------------------------------------------------------------------
    # projects — depends on users, style_profiles
    # ------------------------------------------------------------------
    op.create_table(
        "projects",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("mode", sa.String(20), nullable=False, server_default="operator"),
        sa.Column("doc_type", sa.String(30), nullable=False, server_default="ma_dissertation"),
        sa.Column("title", sa.String(300), nullable=False, server_default="Untitled Project"),
        sa.Column("status", sa.String(30), nullable=False, server_default="formatting"),
        sa.Column("format_profile", sa.String(30), nullable=False, server_default="tn_university"),
        sa.Column(
            "style_profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("style_profiles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("meta", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("front_matter", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("chapters", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("works_cited", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("archived", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_projects_user_id", "projects", ["user_id"])

    # ------------------------------------------------------------------
    # sources — depends on projects, users
    # ------------------------------------------------------------------
    op.create_table(
        "sources",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("fields", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("verified", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("verify_note", sa.Text, nullable=True),
        sa.Column("consulted_flag", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_sources_project_id", "sources", ["project_id"])
    op.create_index("ix_sources_user_id", "sources", ["user_id"])

    # ------------------------------------------------------------------
    # quotes — depends on sources, projects, users
    # ------------------------------------------------------------------
    op.create_table(
        "quotes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("page_or_loc", sa.String(50), nullable=False, server_default=""),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("verified", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("method", sa.String(20), nullable=False, server_default="pasted"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_quotes_source_id", "quotes", ["source_id"])
    op.create_index("ix_quotes_project_id", "quotes", ["project_id"])
    op.create_index("ix_quotes_user_id", "quotes", ["user_id"])

    # ------------------------------------------------------------------
    # exports — depends on projects, users
    # ------------------------------------------------------------------
    op.create_table(
        "exports",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("format", sa.String(10), nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=True),
        sa.Column("checksum", sa.String(64), nullable=True),
        sa.Column("size_bytes", sa.BigInteger, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("report", postgresql.JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_exports_project_id", "exports", ["project_id"])
    op.create_index("ix_exports_user_id", "exports", ["user_id"])
    # Partial unique index: at most one running export per (project, format).
    op.create_index(
        "uq_exports_project_format_running",
        "exports",
        ["project_id", "format"],
        unique=True,
        postgresql_where=sa.text("status = 'running'"),
    )

    # ------------------------------------------------------------------
    # events — depends on projects (nullable), users
    # ------------------------------------------------------------------
    op.create_table(
        "events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(50), nullable=False),
        sa.Column("data", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_events_project_id", "events", ["project_id"])
    op.create_index("ix_events_user_id", "events", ["user_id"])


def downgrade() -> None:
    # Drop in reverse FK-safe order: dependants first.
    op.drop_index("ix_events_user_id", table_name="events")
    op.drop_index("ix_events_project_id", table_name="events")
    op.drop_table("events")

    op.drop_index("uq_exports_project_format_running", table_name="exports")
    op.drop_index("ix_exports_user_id", table_name="exports")
    op.drop_index("ix_exports_project_id", table_name="exports")
    op.drop_table("exports")

    op.drop_index("ix_quotes_user_id", table_name="quotes")
    op.drop_index("ix_quotes_project_id", table_name="quotes")
    op.drop_index("ix_quotes_source_id", table_name="quotes")
    op.drop_table("quotes")

    op.drop_index("ix_sources_user_id", table_name="sources")
    op.drop_index("ix_sources_project_id", table_name="sources")
    op.drop_table("sources")

    op.drop_index("ix_projects_user_id", table_name="projects")
    op.drop_table("projects")

    op.drop_index("ix_style_profiles_user_id", table_name="style_profiles")
    op.drop_table("style_profiles")
