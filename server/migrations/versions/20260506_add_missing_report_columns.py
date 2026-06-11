"""Add missing columns: recipients_json and result_pdf_path

Revision ID: 20260506_add_missing_report_columns
Revises: 56bf0bd40db8
Create Date: 2026-05-06

NOTE: This migration is intentionally a no-op.
Both columns were already added by 20260505_unified_report_features:
- recipients_json on report_schedules (via op.add_column in that migration)
- result_pdf_path on report_generation_jobs (inside the CREATE TABLE statement)
This file is kept to preserve the migration chain. This is a bug fix, not a schema change.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20260506_missing_cols'
down_revision = '56bf0bd40db8'
branch_labels = None
depends_on = None


def upgrade():
    pass  # columns already added by 20260505_unified_report_features


def downgrade():
    pass  # nothing to undo
