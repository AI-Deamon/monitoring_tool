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
    
    # Add os_edition column to asset_info
    op.add_column(
        'asset_info',
        sa.Column('os_edition', sa.String(50), nullable=True)
    )
    
    # Add os_sku column to asset_info
    op.add_column(
        'asset_info',
        sa.Column('os_sku', sa.Integer, nullable=True)
    )
    
    # Create index on os_edition for faster EOL queries
    op.create_index(
        'ix_asset_info_os_edition',
        'asset_info',
        ['os_edition'],
        unique=False
    )
    
    print("[MIGRATION] Added os_edition and os_sku columns to asset_info")


def downgrade():
    """Remove EOL enhancement fields from asset_info table."""
    
    # Drop index first
    op.drop_index('ix_asset_info_os_edition', table_name='asset_info')
    
    # Drop columns
    op.drop_column('asset_info', 'os_sku')
    op.drop_column('asset_info', 'os_edition')
    
    print("[MIGRATION] Removed os_edition and os_sku columns from asset_info")
