"""System-scheduled jobs: jobs.user_id becomes nullable.

The daily retention sweep (and any future system-initiated job) has no
requesting user. Dropping NOT NULL is additive and zero-downtime: existing
rows keep their user_id, application code always sets it for user-initiated
jobs.

Revision ID: 0029
Revises: 0028
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def _column_is_nullable() -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for col in inspector.get_columns("jobs"):
        if col["name"] == "user_id":
            return bool(col.get("nullable"))
    return False


def upgrade() -> None:
    if not _column_is_nullable():
        op.alter_column("jobs", "user_id", existing_type=sa.dialects.postgresql.UUID(), nullable=True)


def downgrade() -> None:
    # Backfill would be required to restore NOT NULL; delete system jobs first.
    op.execute("DELETE FROM jobs WHERE user_id IS NULL")
    op.alter_column("jobs", "user_id", existing_type=sa.dialects.postgresql.UUID(), nullable=False)
