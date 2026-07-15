"""Research-donation consent (docs/LLD.md 3.8).

Revision ID: 0026
Revises: 0025

Adds ``research_consents`` (brand-new, model-driven create) including the partial
unique index that permits re-grant after revocation. No existing table altered.
A separate table from the existing ``consent_records`` (privacy-notice
acceptance), which has a different lifecycle.
"""

from __future__ import annotations

from alembic import op

from app.db.session import Base
import app.models  # noqa: F401 -- registers new tables on Base metadata


revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.tables["research_consents"].create(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    Base.metadata.tables["research_consents"].drop(op.get_bind(), checkfirst=True)
