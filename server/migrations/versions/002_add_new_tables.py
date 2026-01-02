"""Add DomainActiveSession and AgentPolicy tables

Revision ID: 002_add_new_tables
Revises: 001_initial_migration
Create Date: 2025-04-12 12:15:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '002_add_new_tables'
down_revision = '001_initial_migration'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Create domain_active_sessions table
    op.create_table('domain_active_sessions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('agent_id', sa.String(length=128), nullable=True),
    sa.Column('domain', sa.String(length=512), nullable=True),
    sa.Column('start', sa.DateTime(), nullable=True),
    sa.Column('end', sa.DateTime(), nullable=True),
    sa.Column('duration_seconds', sa.Integer(), nullable=True),
    sa.Column('browser', sa.String(length=128), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_domain_active_sessions_agent_id', 'domain_active_sessions', ['agent_id'], unique=False)

    # Create agent_policies table
    op.create_table('agent_policies',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('agent_id', sa.String(length=128), nullable=True),
    sa.Column('version', sa.Integer(), nullable=True),
    sa.Column('config_json', sa.JSON(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_agent_policies_agent_id', 'agent_policies', ['agent_id'], unique=False)

def downgrade() -> None:
    # Drop agent_policies table
    op.drop_index('ix_agent_policies_agent_id', table_name='agent_policies')
    op.drop_table('agent_policies')

    # Drop domain_active_sessions table
    op.drop_index('ix_domain_active_sessions_agent_id', table_name='domain_active_sessions')
    op.drop_table('domain_active_sessions')
