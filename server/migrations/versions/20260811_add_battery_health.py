"""add battery health columns to asset_info

The dashboard displays BIOS version, which is of little operational value to an
IT fleet. This replaces that surface area with battery health telemetry:
design vs. full charge capacity (health %), current charge (%), and cycle count.

The agent already collects this from root\\WMI (MSBatteryClassStaticData /
MSBatteryClassStatus). These four columns are where the server stores it.
Desktops with no battery simply leave the columns NULL.

Revision ID: 20260811_add_battery_health
Revises: 20260807_widen_app_inv_uniq
Create Date: 2026-08-11
"""
import sqlalchemy as sa
from alembic import op

revision = '20260811_add_battery_health'
down_revision = '20260807_widen_app_inv_uniq'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'asset_info',
        sa.Column('battery_name', sa.String(length=255), nullable=True),
    )
    op.add_column(
        'asset_info',
        sa.Column('battery_health_percent', sa.Float, nullable=True),
    )
    op.add_column(
        'asset_info',
        sa.Column('battery_charge_percent', sa.Float, nullable=True),
    )
    op.add_column(
        'asset_info',
        sa.Column('battery_cycle_count', sa.Integer, nullable=True),
    )


def downgrade():
    op.drop_column('asset_info', 'battery_cycle_count')
    op.drop_column('asset_info', 'battery_charge_percent')
    op.drop_column('asset_info', 'battery_health_percent')
    op.drop_column('asset_info', 'battery_name')
