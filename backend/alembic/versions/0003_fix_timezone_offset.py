"""fix timezone double-offset in all timestamp columns

PostgreSQL was running with TZ=Asia/Shanghai while the app stored
timezone-aware UTC datetimes into TIMESTAMP WITHOUT TIME ZONE columns.
PG converted UTC → Shanghai (+8h) before stripping tzinfo, causing all
stored timestamps to be 8 hours ahead of actual UTC.

This migration subtracts 8 hours from every timestamp column to restore
correct UTC values.

Revision ID: 0003_fix_tz
Revises: 0002_rm_miniflux
Create Date: 2026-02-14
"""
from alembic import op

revision = "0003_fix_tz"
down_revision = "0002_rm_miniflux"
branch_labels = None
depends_on = None


def upgrade():
    # Dynamically find and fix ALL timestamp columns in application tables
    # (exclude Procrastinate internal tables which manage their own timestamps)
    op.execute("""
        DO $$
        DECLARE
            r RECORD;
        BEGIN
            FOR r IN
                SELECT table_name, column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND data_type = 'timestamp without time zone'
                  AND table_name NOT LIKE 'procrastinate_%'
            LOOP
                EXECUTE format(
                    'UPDATE %I SET %I = %I - interval ''8 hours'' WHERE %I IS NOT NULL',
                    r.table_name, r.column_name, r.column_name, r.column_name
                );
            END LOOP;
        END $$;
    """)


def downgrade():
    # Add 8 hours back to restore Shanghai-time values
    op.execute("""
        DO $$
        DECLARE
            r RECORD;
        BEGIN
            FOR r IN
                SELECT table_name, column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND data_type = 'timestamp without time zone'
                  AND table_name NOT LIKE 'procrastinate_%'
            LOOP
                EXECUTE format(
                    'UPDATE %I SET %I = %I + interval ''8 hours'' WHERE %I IS NOT NULL',
                    r.table_name, r.column_name, r.column_name, r.column_name
                );
            END LOOP;
        END $$;
    """)
