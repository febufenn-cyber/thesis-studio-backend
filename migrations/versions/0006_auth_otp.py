"""auth_tokens: kind + attempts columns for email-OTP login.

Revision ID: 0006
Revises: 0005
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "auth_tokens",
        sa.Column("kind", sa.String(10), nullable=False, server_default="magic"),
    )
    op.add_column(
        "auth_tokens",
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("auth_tokens", "attempts")
    op.drop_column("auth_tokens", "kind")
