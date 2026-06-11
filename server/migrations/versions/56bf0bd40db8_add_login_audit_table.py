"""add login_audit table

Revision ID: 56bf0bd40db8
Revises: 20260505_unified_report_features
Create Date: 2026-05-05 16:55:51.116316

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '56bf0bd40db8'
down_revision: Union[str, Sequence[str], None] = '20260505_unified_report_features'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'login_audit',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('username', sa.String(100), nullable=False),
        sa.Column('auth_type', sa.String(20), nullable=False, server_default='local'),
        sa.Column('ip_address', sa.String(45), nullable=True),
        sa.Column('user_agent', sa.Text(), nullable=True),
        sa.Column('success', sa.Boolean(), nullable=False),
        sa.Column('failure_reason', sa.String(255), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['dashboard_users.id'], name=op.f('fk_login_audit_user_id'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('login_audit_pkey'))
    )
    op.create_index(op.f('ix_login_audit_user_id'), 'login_audit', ['user_id'], unique=False)
    op.create_index(op.f('ix_login_audit_created_at'), 'login_audit', ['created_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_login_audit_created_at'), table_name='login_audit')
    op.drop_index(op.f('ix_login_audit_user_id'), table_name='login_audit')
    op.drop_table('login_audit')
