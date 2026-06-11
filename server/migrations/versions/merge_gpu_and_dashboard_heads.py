"""Merge heads: gpu_multi_array_001 and 20260506_dash_mv_views

Revision ID: merge_gpu_and_dashboard_heads
Revises: gpu_multi_array_001, 20260506_dash_mv_views
Create Date: 2026-05-18

Merges the GPU array changes with the dashboard analytics views.
"""
from alembic import op
import sqlalchemy as sa


revision = 'merge_gpu_and_dashboard_heads'
down_revision = ('gpu_multi_array_001', '20260506_dash_mv_views')
branch_labels = None
depends_on = None


def upgrade():
    # This is a merge migration - no schema changes needed
    # Both parent migrations have already made their changes
    pass


def downgrade():
    # No downgrade for merge migrations
    pass