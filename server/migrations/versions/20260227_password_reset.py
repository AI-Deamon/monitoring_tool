"""Add email field and password reset functionality

Revision ID: 20260227_password_reset
Revises: 20260227_screentime_daily_cap_guard
Create Date: 2026-02-27 12:45:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers
revision = '20260227_password_reset'
down_revision = '20260227_daily_cap'
branch_labels = None
depends_on = None

def upgrade():
    # Add email field to dashboard_users
    op.add_column('dashboard_users', 
                  sa.Column('email', sa.String(255), nullable=True))
    op.add_column('dashboard_users',
                  sa.Column('email_verified', sa.Boolean, default=False))
    
    # Create password_reset_tokens table
    op.create_table('password_reset_tokens',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('user_id', sa.Integer, sa.ForeignKey('dashboard_users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('token_hash', sa.String(255), nullable=False),
        sa.Column('expires_at', sa.DateTime, nullable=False),
        sa.Column('used_at', sa.DateTime, nullable=True),
        sa.Column('created_at', sa.DateTime, server_default=text('CURRENT_TIMESTAMP')),
        
        # Indexes for performance
        sa.Index('idx_token_hash', 'token_hash'),
        sa.Index('idx_expires_at', 'expires_at'),
        sa.Index('idx_user_id', 'user_id')
    )

def downgrade():
    # Drop table and columns
    op.drop_table('password_reset_tokens')
    op.drop_column('dashboard_users', 'email_verified')
    op.drop_column('dashboard_users', 'email')
