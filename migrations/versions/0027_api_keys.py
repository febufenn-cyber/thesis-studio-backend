"""Public API keys (docs/LLD_MISSING_FEATURES.md MF6).

Revision ID: 0027
Revises: 0026

Adds the ``api_keys`` table (brand-new, model-driven create). No existing table
is altered.
"""

from __future__ import annotations

from alembic import op

from app.db.session import Base
import app.models  # noqa: F401 -- registers new tables on Base metadata


revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.tables["api_keys"].create(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    Base.metadata.tables["api_keys"].drop(op.get_bind(), checkfirst=True)
