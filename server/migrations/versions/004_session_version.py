"""add session_version to users

Revision ID: 004_session_version
Revises: 003_add_api_key_auth
Create Date: 2026-03-04 17:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '004_session_version'
down_revision = '003_add_api_key_auth'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Add session_version to dashboard_users table
    op.add_column('dashboard_users', sa.Column('session_version', sa.Integer(), nullable=True))
    
    # Initialize existing users with session_version 1
    op.execute("UPDATE dashboard_users SET session_version = 1")
    
    # Make it non-nullable after setting defaults
    op.alter_column('dashboard_users', 'session_version', existing_type=sa.Integer(), nullable=False)

def downgrade() -> None:
    # Remove the column
    op.drop_column('dashboard_users', 'session_version')
