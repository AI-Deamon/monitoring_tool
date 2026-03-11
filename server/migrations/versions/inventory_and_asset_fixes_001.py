"""Add missing fields to app_inventory and asset_info

Revision ID: inventory_and_asset_fixes_001
Revises: eol_enhancement_001
Create Date: 2026-02-13

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'inventory_and_asset_fixes_001'
down_revision = 'eol_enhancement_001'
branch_labels = None
depends_on = None


def upgrade():
    # Guard: app_inventory column rename and additions
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'app_inventory') THEN
                -- Rename uninstall_string to uninstall_command if old name exists
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'app_inventory' AND column_name = 'uninstall_string'
                ) THEN
                    ALTER TABLE app_inventory RENAME COLUMN uninstall_string TO uninstall_command;
                END IF;
                -- Add architecture if missing
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'app_inventory' AND column_name = 'architecture'
                ) THEN
                    ALTER TABLE app_inventory ADD COLUMN architecture VARCHAR(50);
                END IF;
                -- Add estimated_size_kb if missing
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'app_inventory' AND column_name = 'estimated_size_kb'
                ) THEN
                    ALTER TABLE app_inventory ADD COLUMN estimated_size_kb BIGINT;
                END IF;
            END IF;
        END $$;
    """)
    
    print("[MIGRATION] Updated app_inventory schema (guarded)")


def downgrade():
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'app_inventory') THEN
                ALTER TABLE app_inventory DROP COLUMN IF EXISTS estimated_size_kb;
                ALTER TABLE app_inventory DROP COLUMN IF EXISTS architecture;
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'app_inventory' AND column_name = 'uninstall_command'
                ) THEN
                    ALTER TABLE app_inventory RENAME COLUMN uninstall_command TO uninstall_string;
                END IF;
            END IF;
        END $$;
    """)
    
    print("[MIGRATION] Reverted app_inventory schema changes")
