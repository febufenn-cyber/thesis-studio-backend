"""Partial unique index: at most one in-flight compile per session.

Closes the TOCTOU window in the compile route's 409 guard — two racing
POST /sessions/{id}/compile requests could both pass the SELECT check and
insert two 'compiling' File rows. With this index the second INSERT raises
IntegrityError (mapped to 409 by the global handler).

Any rows still 'compiling' at migration time belong to jobs killed by a
restart (the deploy itself restarts the server), so they are marked failed
first — same semantics as the startup sweep in app.main.

Revision ID: 0004
Revises: 0003
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE files SET status = 'failed', "
        "error_message = 'Server restarted during compile.' "
        "WHERE status = 'compiling'"
    )
    op.create_index(
        "uq_files_session_compiling",
        "files",
        ["session_id"],
        unique=True,
        postgresql_where=sa.text("status = 'compiling'"),
    )


def downgrade() -> None:
    op.drop_index("uq_files_session_compiling", table_name="files")
