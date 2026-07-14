"""Quotation verification (docs/LLD.md 3.3).

Revision ID: 0024
Revises: 0023

Adds ``quote_verifications`` (brand-new table, model-driven create) and three
optional ``sources.artifact_*`` columns for a stored source artifact. The
``sources`` columns use the 0019 guard: on a fresh DB the model-driven create of
``sources`` already materialises them, so each add is guarded on the live column
set to avoid DuplicateColumnError.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.db.session import Base
import app.models  # noqa: F401 -- registers new tables on Base metadata


revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None

_SOURCE_COLUMNS: tuple[tuple[str, sa.types.TypeEngine], ...] = (
    ("artifact_storage_key", sa.String(length=700)),
    ("artifact_mime_type", sa.String(length=150)),
    ("artifact_checksum", sa.String(length=64)),
)


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    Base.metadata.tables["quote_verifications"].create(op.get_bind(), checkfirst=True)
    existing = _columns("sources")
    for name, coltype in _SOURCE_COLUMNS:
        if name not in existing:
            op.add_column("sources", sa.Column(name, coltype, nullable=True))


def downgrade() -> None:
    existing = _columns("sources")
    for name, _coltype in reversed(_SOURCE_COLUMNS):
        if name in existing:
            op.drop_column("sources", name)
    Base.metadata.tables["quote_verifications"].drop(op.get_bind(), checkfirst=True)
