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
    # --- app_inventory updates ---
    # Rename uninstall_string to uninstall_command to match model
    op.alter_column('app_inventory', 'uninstall_string', new_column_name='uninstall_command')
    
    # Add missing ones
    op.add_column('app_inventory', sa.Column('architecture', sa.String(length=50), nullable=True))
    op.add_column('app_inventory', sa.Column('estimated_size_kb', sa.BigInteger(), nullable=True))
    
    print("[MIGRATION] Updated app_inventory schema")


def downgrade():
    # --- app_inventory downgrades ---
    op.drop_column('app_inventory', 'estimated_size_kb')
    op.drop_column('app_inventory', 'architecture')
    op.alter_column('app_inventory', 'uninstall_command', new_column_name='uninstall_string')
    
    print("[MIGRATION] Reverted app_inventory schema changes")
