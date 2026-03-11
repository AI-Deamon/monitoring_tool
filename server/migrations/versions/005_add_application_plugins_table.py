"""Add application plugins inventory table

Revision ID: 005_add_app_plugins
Revises: 004_add_browser_extensions_table
Create Date: 2026-02-13

Tracks plugins for applications like Office, Adobe, Visual Studio, etc.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '005_add_app_plugins'
down_revision = '004_add_browser_extensions_table'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'application_plugins',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('agent_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('plugin_type', sa.String(50), nullable=False),
        sa.Column('name', sa.String(255), nullable=True),
        sa.Column('version', sa.String(100), nullable=True),
        sa.Column('publisher', sa.String(255), nullable=True),
        sa.Column('install_path', sa.String(500), nullable=True),
        sa.Column('host_application', sa.String(255), nullable=True),
        sa.Column('enabled', sa.Boolean(), server_default='true'),
        sa.Column('first_detected', sa.DateTime(), nullable=True),
        sa.Column('last_updated', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.agent_id'], ondelete='CASCADE'),
        sa.UniqueConstraint('agent_id', 'plugin_type', 'name', 'install_path',
                           name='uq_plugin_agent_type_name_path')
    )
    op.create_index('ix_application_plugins_agent_id', 'application_plugins', ['agent_id'])
    print("[MIGRATION] Created application_plugins table")


def downgrade():
    op.drop_index('ix_application_plugins_agent_id', table_name='application_plugins')
    op.drop_table('application_plugins')
    print("[MIGRATION] Dropped application_plugins table")
