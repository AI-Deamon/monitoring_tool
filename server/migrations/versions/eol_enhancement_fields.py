"""Add EOL enhancement fields for better lifecycle tracking

Revision ID: eol_enhancement_001
Revises: d20081a6c299
Create Date: 2026-02-13

Changes:
- Add os_edition and os_sku to asset_info for Windows edition detection
- These fields enable better EOL matching for Windows LTSC, Enterprise, etc.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'eol_enhancement_001'
down_revision = 'd20081a6c299'
branch_labels = None
depends_on = None


def upgrade():
    """Add EOL enhancement fields to asset_info table."""
    # Guard: asset_info may not exist on fresh DBs (created later in the chain)
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'asset_info') THEN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'asset_info' AND column_name = 'os_edition'
                ) THEN
                    ALTER TABLE asset_info ADD COLUMN os_edition VARCHAR(50);
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'asset_info' AND column_name = 'os_sku'
                ) THEN
                    ALTER TABLE asset_info ADD COLUMN os_sku INTEGER;
                END IF;
            END IF;
        END $$;
    """)
    
    # Create index only if table and column exist
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'asset_info') THEN
                CREATE INDEX IF NOT EXISTS ix_asset_info_os_edition ON asset_info(os_edition);
            END IF;
        END $$;
    """)
    
    print("[MIGRATION] Added os_edition and os_sku columns to asset_info (if table exists)")


def downgrade():
    """Remove EOL enhancement fields from asset_info table."""
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'asset_info') THEN
                DROP INDEX IF EXISTS ix_asset_info_os_edition;
                ALTER TABLE asset_info DROP COLUMN IF EXISTS os_sku;
                ALTER TABLE asset_info DROP COLUMN IF EXISTS os_edition;
            END IF;
        END $$;
    """)
    
    print("[MIGRATION] Removed os_edition and os_sku columns from asset_info")
