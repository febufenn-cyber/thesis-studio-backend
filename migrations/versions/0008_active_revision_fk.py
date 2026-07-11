"""Enforce projects.active_revision_id.

Revision ID: 0008
Revises: 0007
"""

from __future__ import annotations

from alembic import op


revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_foreign_key(
        "fk_projects_active_revision",
        "projects",
        "manuscript_revisions",
        ["active_revision_id"],
        ["id"],
        ondelete="SET NULL",
        use_alter=True,
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_projects_active_revision",
        "projects",
        type_="foreignkey",
    )
