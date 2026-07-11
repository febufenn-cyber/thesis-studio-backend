"""Bridge immutable institutional profile versions to the existing renderer.

Revision ID: 0016
Revises: 0015
"""

from __future__ import annotations

from alembic import op


revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION phase4_pin_renderer_profile()
        RETURNS trigger AS $$
        DECLARE
            profile_row institutional_profile_versions%ROWTYPE;
            generated_style_id uuid;
        BEGIN
            IF NEW.institutional_profile_version_id IS NULL THEN
                RETURN NEW;
            END IF;
            IF TG_OP = 'UPDATE'
               AND NEW.institutional_profile_version_id IS NOT DISTINCT FROM OLD.institutional_profile_version_id
               AND NEW.style_profile_id IS NOT NULL THEN
                RETURN NEW;
            END IF;

            IF NEW.institution_id IS NULL THEN
                SELECT institution_id INTO NEW.institution_id
                FROM users
                WHERE id = NEW.user_id;
            END IF;

            SELECT * INTO profile_row
            FROM institutional_profile_versions
            WHERE id = NEW.institutional_profile_version_id
              AND state = 'published';

            IF NOT FOUND THEN
                RAISE EXCEPTION 'Institutional profile must exist and be published before pinning';
            END IF;
            IF NEW.institution_id IS DISTINCT FROM profile_row.institution_id THEN
                RAISE EXCEPTION 'Institutional profile belongs to another tenant';
            END IF;

            INSERT INTO style_profiles (id, user_id, name, base, data, created_at)
            VALUES (
                gen_random_uuid(),
                NEW.user_id,
                'Institutional ' || profile_row.label || ' v' || profile_row.version,
                profile_row.base_profile,
                profile_row.profile_data,
                now()
            )
            RETURNING id INTO generated_style_id;

            NEW.style_profile_id := generated_style_id;
            NEW.format_profile := profile_row.base_profile;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_phase4_pin_renderer_profile
        BEFORE INSERT OR UPDATE OF institutional_profile_version_id ON projects
        FOR EACH ROW
        EXECUTE FUNCTION phase4_pin_renderer_profile();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_phase4_pin_renderer_profile ON projects")
    op.execute("DROP FUNCTION IF EXISTS phase4_pin_renderer_profile()")
