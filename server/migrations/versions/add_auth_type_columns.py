"""
Add auth_type and ad_object_guid to dashboard_users.

Revision ID: 20260415_add_auth_type
Revises: 1eb7f9e3f23e
Create Date: 2026-04-15

Adds support for Active Directory authentication by adding:
- auth_type: 'local' or 'ad'
- ad_object_guid: AD object GUID for user
"""

from alembic import op
import sqlalchemy as sa


revision = "20260415_add_auth_type"
down_revision = "1eb7f9e3f23e"
branch_labels = None
depends_on = None


def upgrade():
    # Add auth_type column
    op.add_column(
        "dashboard_users",
        sa.Column("auth_type", sa.String(20), nullable=True, server_default="local"),
    )

    # Add ad_object_guid column
    op.add_column(
        "dashboard_users", sa.Column("ad_object_guid", sa.String(100), nullable=True)
    )


def downgrade():
    op.drop_column("dashboard_users", "ad_object_guid")
    op.drop_column("dashboard_users", "auth_type")
