"""Ensure new projects inherit the student's selected institution.

Revision ID: 0013
Revises: 0012
"""

from __future__ import annotations

from alembic import op


revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION phase4_set_project_institution()
        RETURNS trigger AS $$
        BEGIN
            IF NEW.institution_id IS NULL THEN
                SELECT institution_id INTO NEW.institution_id
                FROM users
                WHERE id = NEW.user_id;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_phase4_set_project_institution
        BEFORE INSERT OR UPDATE OF user_id, institution_id ON projects
        FOR EACH ROW
        EXECUTE FUNCTION phase4_set_project_institution();
        """
    )
    op.execute(
        """
        UPDATE projects p
        SET institution_id = u.institution_id
        FROM users u
        WHERE p.user_id = u.id AND p.institution_id IS NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_phase4_set_project_institution ON projects")
    op.execute("DROP FUNCTION IF EXISTS phase4_set_project_institution()")
