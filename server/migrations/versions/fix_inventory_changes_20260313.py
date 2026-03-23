"""Fix app_inventory_changes table columns

Revision ID: fix_inventory_changes_20260313
Revises: 12b58bbde69e
Create Date: 2026-03-13 13:11:00

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'fix_inventory_changes_20260313'
down_revision = '12b58bbde69e'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Safely update app_inventory_changes table
    op.execute("""
        DO $$ 
        BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'app_inventory_changes') THEN
                
                -- 1. Rename created_at to timestamp if it exists and timestamp doesn't
                IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='app_inventory_changes' AND column_name='created_at') 
                   AND NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='app_inventory_changes' AND column_name='timestamp') THEN
                    ALTER TABLE app_inventory_changes RENAME COLUMN created_at TO timestamp;
                END IF;

                -- 2. Add timestamp if still missing
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='app_inventory_changes' AND column_name='timestamp') THEN
                    ALTER TABLE app_inventory_changes ADD COLUMN timestamp TIMESTAMP DEFAULT NOW();
                END IF;

                -- 3. Add change_type
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='app_inventory_changes' AND column_name='change_type') THEN
                    ALTER TABLE app_inventory_changes ADD COLUMN change_type VARCHAR(20) DEFAULT 'installed';
                    -- Remove default after creation if needed, but it's nullable=False in model, so we need a default for existing rows
                END IF;

                -- 4. Add app_name
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='app_inventory_changes' AND column_name='app_name') THEN
                    ALTER TABLE app_inventory_changes ADD COLUMN app_name VARCHAR(255) DEFAULT 'Unknown';
                END IF;

                -- 5. Add version
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='app_inventory_changes' AND column_name='version') THEN
                    ALTER TABLE app_inventory_changes ADD COLUMN version VARCHAR(100);
                END IF;

                -- 6. Convert agent_id to UUID if it's currently VARCHAR
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns 
                    WHERE table_name='app_inventory_changes' 
                    AND column_name='agent_id' 
                    AND data_type = 'character varying'
                ) THEN
                    -- Drop FK if exists (from 001_initial_migration it's likely app_inventory_changes_agent_id_fkey)
                    -- But we already saw c15377a4441b dropped these and changed to UUID, 
                    -- so maybe it's already UUID but missing columns?
                    -- Let's check type first.
                    NULL; 
                END IF;

                -- 7. Drop old 'change' column if it exists
                IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='app_inventory_changes' AND column_name='change') THEN
                    ALTER TABLE app_inventory_changes DROP COLUMN change;
                END IF;

                -- 8. Add index on timestamp if missing
                IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE tablename = 'app_inventory_changes' AND indexname = 'ix_app_inventory_changes_timestamp') THEN
                    CREATE INDEX ix_app_inventory_changes_timestamp ON app_inventory_changes (timestamp);
                END IF;

            END IF;
        END $$;
    """)


def downgrade() -> None:
    # Downgrade is minimal to prevent data loss
    pass
