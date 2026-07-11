"""Create the deferred attestation-to-submission constraint explicitly.

Revision ID: 0014
Revises: 0013
"""

from __future__ import annotations

from alembic import op


revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


_CONSTRAINT = "fk_attestations_submission_package_id_submission_packages"


def upgrade() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = '{_CONSTRAINT}'
                  AND conrelid = 'attestations'::regclass
            ) THEN
                ALTER TABLE attestations
                ADD CONSTRAINT {_CONSTRAINT}
                FOREIGN KEY (submission_package_id)
                REFERENCES submission_packages(id)
                ON DELETE CASCADE;
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute(
        f"ALTER TABLE attestations DROP CONSTRAINT IF EXISTS {_CONSTRAINT}"
    )
