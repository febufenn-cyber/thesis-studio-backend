"""AI provenance — AI Use Statements (docs/LLD.md 3.1).

Revision ID: 0023
Revises: 0022

Adds the ``ai_use_statements`` table. Model-driven create (0012/0015/0017
pattern); the table is brand new so there is no duplicate-column risk. No
existing table is altered. The ``ai_edited`` block origin and the disclosure
rollup are canonical/JSON concerns and need no schema change.
"""

from __future__ import annotations

from alembic import op

from app.db.session import Base
import app.models  # noqa: F401 -- registers new tables on Base metadata


revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.tables["ai_use_statements"].create(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    Base.metadata.tables["ai_use_statements"].drop(op.get_bind(), checkfirst=True)
