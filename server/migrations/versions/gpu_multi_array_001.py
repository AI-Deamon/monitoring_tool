"""Replace GPU fields with GPU array for multi-GPU support

Revision ID: gpu_multi_array_001
Revises: fix_inventory_changes_20260313
Create Date: 2026-05-18

This migration:
1. Adds gpus_json column to asset_info (stores [{name, memory_gb}])
2. Drops gpu_name and gpu_memory_gb columns
3. Runs in a transaction
"""
from alembic import op
import sqlalchemy as sa


revision = 'gpu_multi_array_001'
down_revision = 'fix_inventory_changes_20260313'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'asset_info' AND column_name = 'gpu_name'
            ) THEN
                ALTER TABLE asset_info RENAME COLUMN gpu_name TO gpu_name_deprecated;
            END IF;
            
            IF EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'asset_info' AND column_name = 'gpu_memory_gb'
            ) THEN
                ALTER TABLE asset_info RENAME COLUMN gpu_memory_gb TO gpu_memory_gb_deprecated;
            END IF;
            
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'asset_info' AND column_name = 'gpus_json'
            ) THEN
                ALTER TABLE asset_info ADD COLUMN gpus_json TEXT;
            END IF;
        END $$;
    """)


def downgrade():
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'asset_info' AND column_name = 'gpus_json'
            ) THEN
                ALTER TABLE asset_info DROP COLUMN IF EXISTS gpus_json;
            END IF;
            
            IF EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'asset_info' AND column_name = 'gpu_name_deprecated'
            ) THEN
                ALTER TABLE asset_info RENAME COLUMN gpu_name_deprecated TO gpu_name;
            END IF;
            
            IF EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'asset_info' AND column_name = 'gpu_memory_gb_deprecated'
            ) THEN
                ALTER TABLE asset_info RENAME COLUMN gpu_memory_gb_deprecated TO gpu_memory_gb;
            END IF;
        END $$;
    """)