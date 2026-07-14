"""Add style-agnostic source_type to the citation registry.

Revision ID: 0021
Revises: 0020
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("source_type", sa.String(length=40), nullable=True))


def downgrade() -> None:
    op.drop_column("sources", "source_type")
