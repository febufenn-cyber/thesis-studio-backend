"""Phase 3 proposal provenance and run idempotency follow-up.

Revision ID: 0011
Revises: 0010
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ai_runs", sa.Column("client_request_id", sa.String(120), nullable=True))
    op.create_unique_constraint(
        "uq_ai_run_client_request", "ai_runs", ["project_id", "client_request_id"]
    )
    op.add_column(
        "ai_proposals",
        sa.Column(
            "human_edited_operations",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("ai_proposals", "human_edited_operations")
    op.drop_constraint("uq_ai_run_client_request", "ai_runs", type_="unique")
    op.drop_column("ai_runs", "client_request_id")
