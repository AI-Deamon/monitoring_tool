"""
Make password_hash nullable for AD authentication support.

Revision ID: 20260415_password_hash_nullable
Revises: 20260415_add_auth_type
Create Date: 2026-04-15

Allows users to be created without a password_hash (for AD auth).
"""

from alembic import op
import sqlalchemy as sa


revision = "20260415_password_hash_nullable"
down_revision = "20260415_add_auth_type"
branch_labels = None
depends_on = None


def upgrade():
    # Make password_hash nullable for AD users
    op.alter_column(
        "dashboard_users", "password_hash", existing_type=sa.String(255), nullable=True
    )


def downgrade():
    # Revert to not nullable (will fail if AD users exist without password)
    op.alter_column(
        "dashboard_users", "password_hash", existing_type=sa.String(255), nullable=False
    )
