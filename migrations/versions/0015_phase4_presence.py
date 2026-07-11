"""Limited project presence heartbeats.

Revision ID: 0015
Revises: 0014
"""

from __future__ import annotations

from alembic import op

from app.db.session import Base
import app.models  # noqa: F401


revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.tables["project_presence"].create(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    Base.metadata.tables["project_presence"].drop(op.get_bind(), checkfirst=True)
