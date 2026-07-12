"""Persist collaboration quotation verification notes.

Revision ID: 0018
Revises: 0017
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("quotes", sa.Column("verify_note", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("quotes", "verify_note")
