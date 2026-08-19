"""Merge heads: 20260619_telemetry_indexes and merge_gpu_and_dashboard_heads

Revision ID: 20260711_merge_tel_gpu
Revises: 20260619_telemetry_indexes, merge_gpu_and_dashboard_heads
Create Date: 2026-07-11

No-op merge to reconcile two diverged heads.
"""
from alembic import op
import sqlalchemy as sa


revision = '20260711_merge_tel_gpu'
down_revision = ('20260619_telemetry_indexes', 'merge_gpu_and_dashboard_heads')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
