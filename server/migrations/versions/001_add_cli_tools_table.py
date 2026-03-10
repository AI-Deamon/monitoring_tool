"""Add CLI tools inventory table

Revision ID: 001_add_cli_tools_table
Revises: inventory_and_asset_fixes_001
Create Date: 2026-02-13

Tracks command-line tools like git, node, python, opencode, etc.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '001_add_cli_tools_table'
down_revision = 'inventory_and_asset_fixes_001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'cli_tools',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('agent_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('version', sa.String(100), nullable=True),
        sa.Column('executable_path', sa.String(500), nullable=True),
        sa.Column('source', sa.String(50), nullable=True),
        sa.Column('publisher', sa.String(255), nullable=True),
        sa.Column('first_detected', sa.DateTime(), nullable=True),
        sa.Column('last_updated', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.agent_id'], ondelete='CASCADE'),
        sa.UniqueConstraint('agent_id', 'name', 'executable_path', name='uq_cli_tool_agent_name_path')
    )
    op.create_index('ix_cli_tools_agent_id', 'cli_tools', ['agent_id'])
    print("[MIGRATION] Created cli_tools table")


def downgrade():
    op.drop_index('ix_cli_tools_agent_id', table_name='cli_tools')
    op.drop_table('cli_tools')
    print("[MIGRATION] Dropped cli_tools table")
