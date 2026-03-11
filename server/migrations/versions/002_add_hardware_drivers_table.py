"""Add hardware drivers inventory table

Revision ID: 002_add_hardware_drivers_table
Revises: 001_add_cli_tools_table
Create Date: 2026-02-13

Tracks system hardware drivers for EOL and security assessment.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '002_add_hardware_drivers_table'
down_revision = '001_add_cli_tools_table'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'hardware_drivers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('agent_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('device_name', sa.String(255), nullable=True),
        sa.Column('driver_name', sa.String(255), nullable=True),
        sa.Column('driver_version', sa.String(100), nullable=True),
        sa.Column('driver_date', sa.Date(), nullable=True),
        sa.Column('manufacturer', sa.String(255), nullable=True),
        sa.Column('device_class', sa.String(100), nullable=True),
        sa.Column('device_id', sa.String(500), nullable=True),
        sa.Column('is_signed', sa.Boolean(), server_default='false'),
        sa.Column('signer', sa.String(255), nullable=True),
        sa.Column('first_detected', sa.DateTime(), nullable=True),
        sa.Column('last_updated', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.agent_id'], ondelete='CASCADE'),
        sa.UniqueConstraint('agent_id', 'device_id', name='uq_driver_agent_device')
    )
    op.create_index('ix_hardware_drivers_agent_id', 'hardware_drivers', ['agent_id'])
    print("[MIGRATION] Created hardware_drivers table")


def downgrade():
    op.drop_index('ix_hardware_drivers_agent_id', table_name='hardware_drivers')
    op.drop_table('hardware_drivers')
    print("[MIGRATION] Dropped hardware_drivers table")
