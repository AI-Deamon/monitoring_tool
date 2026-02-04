"""Create domain_visits table for Column B (Sites Opened).

Revision ID: 006_add_domain_visits
Revises: 005_add_username_to_sessions
Create Date: 2025-12-07
"""
from alembic import op
import sqlalchemy as sa

revision = '006_add_domain_visits'
down_revision = '005_add_username_to_sessions'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'domain_visits',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('agent_id', sa.dialects.postgresql.UUID(), sa.ForeignKey('agents.agent_id'), nullable=False),
        sa.Column('username', sa.String(255), nullable=True),
        sa.Column('domain', sa.String(255), nullable=False),
        sa.Column('url', sa.Text(), nullable=True),
        sa.Column('browser', sa.String(50), nullable=True),
        sa.Column('visited_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_domain_visits_agent_id', 'domain_visits', ['agent_id'])
    op.create_index('ix_domain_visits_agent_date', 'domain_visits', ['agent_id', 'visited_at'])


def downgrade():
    op.drop_table('domain_visits')
