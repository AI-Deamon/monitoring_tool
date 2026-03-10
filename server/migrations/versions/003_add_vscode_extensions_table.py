"""Add VS Code extensions inventory table

Revision ID: 003_add_vscode_extensions_table
Revises: 002_add_hardware_drivers_table
Create Date: 2026-02-13

Tracks VS Code and VS Code Insiders extensions.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '003_add_vscode_extensions_table'
down_revision = '002_add_hardware_drivers_table'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'vscode_extensions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('agent_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('extension_id', sa.String(255), nullable=True),
        sa.Column('display_name', sa.String(255), nullable=True),
        sa.Column('version', sa.String(100), nullable=True),
        sa.Column('publisher', sa.String(255), nullable=True),
        sa.Column('install_path', sa.String(500), nullable=True),
        sa.Column('first_detected', sa.DateTime(), nullable=True),
        sa.Column('last_updated', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.agent_id'], ondelete='CASCADE'),
        sa.UniqueConstraint('agent_id', 'extension_id', name='uq_vscode_ext_agent_ext')
    )
    op.create_index('ix_vscode_extensions_agent_id', 'vscode_extensions', ['agent_id'])
    print("[MIGRATION] Created vscode_extensions table")


def downgrade():
    op.drop_index('ix_vscode_extensions_agent_id', table_name='vscode_extensions')
    op.drop_table('vscode_extensions')
    print("[MIGRATION] Dropped vscode_extensions table")
