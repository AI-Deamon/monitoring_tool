"""Add username column to app_sessions and domain_sessions tables.

Revision ID: 005_add_username_to_sessions
Revises: 004_add_username_to_screentime
Create Date: 2025-12-07
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = '005_add_username_to_sessions'
down_revision = '004_add_username_to_screentime'
branch_labels = None
depends_on = None


def upgrade():
    # Add username to app_sessions
    op.add_column('app_sessions', sa.Column('username', sa.String(255), nullable=True))
    
    # Add username to domain_sessions if it exists and doesn't have the column
    try:
        op.add_column('domain_sessions', sa.Column('username', sa.String(255), nullable=True))
    except Exception:
        pass  # Column might already exist or table might not exist


def downgrade():
    op.drop_column('app_sessions', 'username')
    try:
        op.drop_column('domain_sessions', 'username')
    except Exception:
        pass
