"""add session_version to users

Revision ID: 004_session_version
Revises: 003_add_api_key_auth
Create Date: 2026-03-04 17:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '004_session_version'
down_revision = '003_add_api_key_auth'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Guard: dashboard_users may not exist on fresh DBs (created by df29e57c74bb)
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'dashboard_users') THEN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'dashboard_users' AND column_name = 'session_version'
                ) THEN
                    ALTER TABLE dashboard_users ADD COLUMN session_version INTEGER DEFAULT 1;
                    UPDATE dashboard_users SET session_version = 1;
                    ALTER TABLE dashboard_users ALTER COLUMN session_version SET NOT NULL;
                END IF;
            END IF;
        END $$;
    """)

def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'dashboard_users') THEN
                ALTER TABLE dashboard_users DROP COLUMN IF EXISTS session_version;
            END IF;
        END $$;
    """)
