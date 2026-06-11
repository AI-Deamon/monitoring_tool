"""Add unified report features

Revision ID: 20260505_unified_report_features
Revises: 20260430_report_schedules
Create Date: 2026-05-05
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20260505_unified_report_features'
down_revision = '20260430_report_schedules'
branch_labels = None
depends_on = None


def upgrade():
    # Extend existing report_schedules table with new columns
    op.add_column('report_schedules', sa.Column('include_pdf', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('report_schedules', sa.Column('auto_email', sa.Boolean(), nullable=False, server_default='true'))
    op.add_column('report_schedules', sa.Column('template_name', sa.String(100), nullable=True))
    op.add_column('report_schedules', sa.Column('recipients_json', postgresql.JSONB(), nullable=True, server_default='[]'))

    # New table for async job tracking
    op.create_table(
        'report_generation_jobs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('schedule_id', sa.Integer(), sa.ForeignKey('report_schedules.id', ondelete='SET NULL'), nullable=True),
        sa.Column('report_type', sa.String(20), nullable=False),
        sa.Column('scope', sa.String(20), nullable=False),
        sa.Column('agent_id', sa.String(100), nullable=True),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('progress', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('result_html', sa.Text(), nullable=True),
        sa.Column('result_pdf_path', sa.String(500), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_by', sa.String(100), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_report_jobs_status', 'report_generation_jobs', ['status'])
    op.create_index('ix_report_jobs_created_at', 'report_generation_jobs', ['created_at'])


def downgrade():
    op.drop_index('ix_report_jobs_created_at', 'report_generation_jobs')
    op.drop_index('ix_report_jobs_status', 'report_generation_jobs')
    op.drop_table('report_generation_jobs')
    op.drop_column('report_schedules', 'template_name')
    op.drop_column('report_schedules', 'auto_email')
    op.drop_column('report_schedules', 'include_pdf')
