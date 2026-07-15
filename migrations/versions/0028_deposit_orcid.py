"""External deposit + ORCID (docs/LLD_MISSING_FEATURES.md MF3).

Revision ID: 0028
Revises: 0027

Adds ``deposits`` (brand-new, model-driven create) and two ORCID columns on
``users`` (0019-guarded add_column: on a fresh DB the model-driven create of
``users`` already materialises them, so guard on the live column set).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.db.session import Base
import app.models  # noqa: F401 -- registers new tables on Base metadata


revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None

_USER_COLUMNS: tuple[tuple[str, sa.types.TypeEngine], ...] = (
    ("orcid", sa.String(length=19)),
    ("orcid_verified_at", sa.DateTime(timezone=True)),
)


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    Base.metadata.tables["deposits"].create(op.get_bind(), checkfirst=True)
    existing = _columns("users")
    for name, coltype in _USER_COLUMNS:
        if name not in existing:
            op.add_column("users", sa.Column(name, coltype, nullable=True))


def downgrade() -> None:
    existing = _columns("users")
    for name, _coltype in reversed(_USER_COLUMNS):
        if name in existing:
            op.drop_column("users", name)
    Base.metadata.tables["deposits"].drop(op.get_bind(), checkfirst=True)
