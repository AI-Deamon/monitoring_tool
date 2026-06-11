"""Add report_schedules table

Revision ID: 20260430_report_schedules
Revises: 20260415_password_hash_nullable
Create Date: 2026-04-30
"""
from alembic import op
import sqlalchemy as sa

revision = '20260430_report_schedules'
down_revision = '20260415_password_hash_nullable'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'report_schedules',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('report_type', sa.String(20), nullable=False),   # weekly/monthly/daily
        sa.Column('scope', sa.String(20), nullable=False),          # individual/team
        sa.Column('agent_id', sa.String(100), nullable=True),       # NULL = all agents (team)
        sa.Column('recipients', sa.Text(), nullable=False),          # JSON array of emails
        sa.Column('frequency', sa.String(20), nullable=False),       # daily/weekly/monthly
        sa.Column('day_of_week', sa.Integer(), nullable=True),       # 0=Mon, for weekly
        sa.Column('day_of_month', sa.Integer(), nullable=True),      # 1-28, for monthly
        sa.Column('send_hour', sa.Integer(), default=9, nullable=False),
        sa.Column('enabled', sa.Boolean(), default=True, nullable=False),
        sa.Column('last_run', sa.DateTime(), nullable=True),
        sa.Column('next_run', sa.DateTime(), nullable=True),
        sa.Column('created_by', sa.String(100), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table('report_schedules')
