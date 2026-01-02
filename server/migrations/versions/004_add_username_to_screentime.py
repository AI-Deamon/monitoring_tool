"""Add username to screen_time

Revision ID: 004_add_username_to_screentime
Revises: 003_add_api_key_auth
Create Date: 2025-12-07 13:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '004_add_username_to_screentime'
down_revision = '4c19c566787a'
branch_labels = None
depends_on = None


def upgrade():
    """Add username column to screen_time table."""
    op.add_column('screen_time', sa.Column('username', sa.String(255), nullable=True))


def downgrade():
    """Remove username column from screen_time table."""
    op.drop_column('screen_time', 'username')
