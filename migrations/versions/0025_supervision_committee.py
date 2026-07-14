"""Supervision & committee workflow (docs/LLD.md 3.6).

Revision ID: 0025
Revises: 0024

Adds ``committee_memberships`` and ``block_comments`` (both brand-new,
model-driven create; no existing table altered).
"""

from __future__ import annotations

from alembic import op

from app.db.session import Base
import app.models  # noqa: F401 -- registers new tables on Base metadata


revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None

_TABLES = ("committee_memberships", "block_comments")


def upgrade() -> None:
    bind = op.get_bind()
    for name in _TABLES:
        Base.metadata.tables[name].create(bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for name in reversed(_TABLES):
        Base.metadata.tables[name].drop(bind, checkfirst=True)
