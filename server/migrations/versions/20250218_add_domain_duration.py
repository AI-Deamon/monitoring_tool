"""add domain duration to live status

Revision ID: 20250218_add_domain_duration
Revises: 20250218_add_stored_procedures
Create Date: 2025-02-18 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20250218_add_domain_duration'
down_revision = '20250218_add_stored_procedures'
branch_labels = None
depends_on = None


def upgrade():
    # Add domain_session_start column if not exists
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_name = 'agent_current_status'
            ) THEN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns 
                    WHERE table_name='agent_current_status' AND column_name='domain_session_start'
                ) THEN
                    ALTER TABLE agent_current_status ADD COLUMN domain_session_start TIMESTAMP NULL;
                END IF;
                
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns 
                    WHERE table_name='agent_current_status' AND column_name='domain_duration_seconds'
                ) THEN
                    ALTER TABLE agent_current_status ADD COLUMN domain_duration_seconds INTEGER DEFAULT 0;
                END IF;
            END IF;
        END $$;
    """)


def downgrade():
    op.drop_column('agent_current_status', 'domain_duration_seconds')
    op.drop_column('agent_current_status', 'domain_session_start')
