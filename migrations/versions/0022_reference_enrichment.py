"""Reference enrichment and reconciliation (docs/LLD.md 3.2).

Adds the resolver cache (``resolution_records``), per-field apply provenance
(``source_field_provenance``), and four enrichment columns on ``sources``.

Revision ID: 0022
Revises: 0021

The two new tables are created model-driven (``Base.metadata.tables[name]
.create(..., checkfirst=True)``), matching 0012/0015/0017. The ``sources``
columns are added with the 0019 guard: on a fresh database the model-driven
create of ``sources`` (or ``create_all`` in tests) already materialises every
column the model declares, so an unconditional ``add_column`` would raise
DuplicateColumnError. Each add is therefore guarded on the live column set.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.db.session import Base
import app.models  # noqa: F401 -- registers new tables on Base metadata


revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


_NEW_TABLES = ("resolution_records", "source_field_provenance")

_SOURCE_COLUMNS: tuple[tuple[str, sa.types.TypeEngine], ...] = (
    ("resolution_status", sa.String(length=20)),
    ("retraction_status", sa.String(length=20)),
    ("canonical_key", sa.String(length=120)),
    ("alternate_keys", sa.dialects.postgresql.JSONB()),
)


def _columns(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    for name in _NEW_TABLES:
        Base.metadata.tables[name].create(bind, checkfirst=True)

    existing = _columns("sources")
    for name, coltype in _SOURCE_COLUMNS:
        if name in existing:
            continue
        if name == "alternate_keys":
            op.add_column(
                "sources",
                sa.Column(name, coltype, nullable=False, server_default="[]"),
            )
            # Drop the server_default now that existing rows are backfilled; the
            # ORM supplies ``list`` on insert going forward.
            op.alter_column("sources", name, server_default=None)
        else:
            op.add_column("sources", sa.Column(name, coltype, nullable=True))

    op.create_index(
        "ix_sources_canonical_key", "sources", ["canonical_key"], if_not_exists=True
    )


def downgrade() -> None:
    op.drop_index("ix_sources_canonical_key", table_name="sources", if_exists=True)
    existing = _columns("sources")
    for name, _coltype in reversed(_SOURCE_COLUMNS):
        if name in existing:
            op.drop_column("sources", name)
    bind = op.get_bind()
    for name in reversed(_NEW_TABLES):
        Base.metadata.tables[name].drop(bind, checkfirst=True)
