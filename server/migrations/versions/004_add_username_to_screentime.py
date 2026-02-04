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
    """Add username column to screen_time table if it doesn't exist."""
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name='screen_time' AND column_name='username'
            ) THEN
                ALTER TABLE screen_time ADD COLUMN username VARCHAR(255) NULL;
            END IF;
        END $$;
    """)


def downgrade():
    """Remove username column from screen_time table."""
    op.drop_column('screen_time', 'username')
