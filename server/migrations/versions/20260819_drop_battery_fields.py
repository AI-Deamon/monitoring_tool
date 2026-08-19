"""drop battery charge_percent and cycle_count columns

Both fields turned out unreliable across OEMs/drivers - WMI/powercfg report
current charge % and cycle count inconsistently, and cycle_count in
particular defaulted to 0 with no way to distinguish "unknown" from a real
0. battery_name and battery_health_percent (design vs. full-charge capacity)
stay - health % doesn't depend on either dropped field.

Revision ID: 20260819_drop_battery_fields
Revises: f1ed8d78511e
Create Date: 2026-08-19
"""
import sqlalchemy as sa
from alembic import op

revision = '20260819_drop_battery_fields'
down_revision = 'f1ed8d78511e'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_column('asset_info', 'battery_charge_percent')
    op.drop_column('asset_info', 'battery_cycle_count')


def downgrade():
    op.add_column(
        'asset_info',
        sa.Column('battery_charge_percent', sa.Float, nullable=True),
    )
    op.add_column(
        'asset_info',
        sa.Column('battery_cycle_count', sa.Integer, nullable=True),
    )
