"""Add last_event_at ordering guards to billing customers and invoices.

Revision ID: 0019
Revises: 0018

Idempotent by design. Migration 0017 creates ``billing_customers`` and
``invoices`` from the live model metadata
(``Base.metadata.tables[name].create(...)``), so on a *fresh* database those
tables are already materialised with whatever columns the models currently
declare -- including ``last_event_at``. On a database that ran 0017 *before*
``last_event_at`` was added to the models, the column is absent and must be
added here. Guarding each ``add_column``/``drop_column`` on the live column
set makes this revision correct regardless of which path a given database
took, instead of failing with DuplicateColumnError on fresh installs.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


_TARGETS = ("billing_customers", "invoices")


def _columns(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    for table in _TARGETS:
        if "last_event_at" not in _columns(table):
            op.add_column(
                table,
                sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=True),
            )


def downgrade() -> None:
    for table in reversed(_TARGETS):
        if "last_event_at" in _columns(table):
            op.drop_column(table, "last_event_at")
