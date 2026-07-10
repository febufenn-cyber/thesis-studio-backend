"""file status and nullable r2_key

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-10
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "files",
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="ready",
        ),
    )
    op.add_column(
        "files",
        sa.Column(
            "error_message",
            sa.Text,
            nullable=True,
        ),
    )
    op.alter_column(
        "files",
        "r2_key",
        existing_type=sa.String(500),
        nullable=True,
    )


def downgrade() -> None:
    op.drop_column("files", "error_message")
    op.drop_column("files", "status")
    op.alter_column(
        "files",
        "r2_key",
        existing_type=sa.String(500),
        nullable=False,
    )
