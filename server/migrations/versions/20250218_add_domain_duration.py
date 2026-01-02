"""add domain duration to live status

Revision ID: 20250218_add_domain_duration
Revises: 20250218_add_stored_procedures
Create Date: 2025-02-18 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20250218_add_domain_duration'
down_revision = '20250218_add_stored_procedures'
branch_labels = None
depends_on = None


def upgrade():
    # Add domain_session_start column
    op.add_column('agent_current_status', 
        sa.Column('domain_session_start', sa.DateTime(), nullable=True))
    
    # Add domain_duration_seconds column
    op.add_column('agent_current_status', 
        sa.Column('domain_duration_seconds', sa.Integer(), server_default='0', nullable=True))


def downgrade():
    op.drop_column('agent_current_status', 'domain_duration_seconds')
    op.drop_column('agent_current_status', 'domain_session_start')
