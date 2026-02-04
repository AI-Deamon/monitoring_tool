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
    # Add username to app_sessions if not exists
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name='app_sessions' AND column_name='username'
            ) THEN
                ALTER TABLE app_sessions ADD COLUMN username VARCHAR(255) NULL;
            END IF;
        END $$;
    """)
    
    # Add username to domain_sessions if it exists and doesn't have the column
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.tables 
                WHERE table_name='domain_sessions'
            ) THEN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns 
                    WHERE table_name='domain_sessions' AND column_name='username'
                ) THEN
                    ALTER TABLE domain_sessions ADD COLUMN username VARCHAR(255) NULL;
                END IF;
            END IF;
        END $$;
    """)


def downgrade():
    op.drop_column('app_sessions', 'username')
    try:
        op.drop_column('domain_sessions', 'username')
    except Exception:
        pass
