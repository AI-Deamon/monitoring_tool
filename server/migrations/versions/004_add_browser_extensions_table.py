"""Add browser extensions inventory table

Revision ID: 004_add_browser_extensions_table
Revises: 003_add_vscode_extensions_table
Create Date: 2026-02-13

Tracks browser extensions for Chrome, Firefox, and Edge.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '004_add_browser_extensions_table'
down_revision = '003_add_vscode_extensions_table'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'browser_extensions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('agent_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('browser', sa.String(50), nullable=False),
        sa.Column('extension_id', sa.String(255), nullable=True),
        sa.Column('name', sa.String(255), nullable=True),
        sa.Column('version', sa.String(100), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('enabled', sa.Boolean(), server_default='true'),
        sa.Column('install_date', sa.Date(), nullable=True),
        sa.Column('profile_path', sa.String(500), nullable=True),
        sa.Column('first_detected', sa.DateTime(), nullable=True),
        sa.Column('last_updated', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.agent_id'], ondelete='CASCADE'),
        sa.UniqueConstraint('agent_id', 'browser', 'extension_id', name='uq_browser_ext_agent_browser_ext')
    )
    op.create_index('ix_browser_extensions_agent_id', 'browser_extensions', ['agent_id'])
    print("[MIGRATION] Created browser_extensions table")


def downgrade():
    op.drop_index('ix_browser_extensions_agent_id', table_name='browser_extensions')
    op.drop_table('browser_extensions')
    print("[MIGRATION] Dropped browser_extensions table")
