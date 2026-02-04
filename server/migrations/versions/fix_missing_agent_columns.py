"""Fix missing columns in agents table

Revision ID: fix_missing_agent_columns
Revises: 668a1f8f863e
Create Date: 2026-02-04 11:30:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'fix_missing_agent_columns'
down_revision = '668a1f8f863e'
branch_labels = None
depends_on = None


def upgrade():
    # Add missing columns to agents table
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='agents' AND column_name='agent_name') THEN
                ALTER TABLE agents ADD COLUMN agent_name VARCHAR(255);
            END IF;
            
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='agents' AND column_name='os_build') THEN
                ALTER TABLE agents ADD COLUMN os_build INTEGER;
            END IF;
            
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='agents' AND column_name='windows_edition') THEN
                ALTER TABLE agents ADD COLUMN windows_edition VARCHAR(50);
            END IF;
            
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='agents' AND column_name='architecture') THEN
                ALTER TABLE agents ADD COLUMN architecture VARCHAR(50);
            END IF;
            
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='agents' AND column_name='api_key') THEN
                ALTER TABLE agents ADD COLUMN api_key VARCHAR(128);
            END IF;
            
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='agents' AND column_name='operational_status') THEN
                ALTER TABLE agents ADD COLUMN operational_status VARCHAR(50) DEFAULT 'NORMAL';
            END IF;
            
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='agents' AND column_name='status_reason') THEN
                ALTER TABLE agents ADD COLUMN status_reason TEXT;
            END IF;
            
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='agents' AND column_name='last_status_change') THEN
                ALTER TABLE agents ADD COLUMN last_status_change TIMESTAMP;
            END IF;
            
            if NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='agents' AND column_name='diagnostics_json') THEN
                ALTER TABLE agents ADD COLUMN diagnostics_json TEXT;
            END IF;
            
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='agents' AND column_name='api_token') THEN
                ALTER TABLE agents ADD COLUMN api_token TEXT;
            END IF;
        END $$;
    """)


def downgrade():
    # We generally don't drop columns in fix migrations to avoid data loss
    pass
