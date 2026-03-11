"""Add portable applications inventory table

Revision ID: 006_add_portable_apps
Revises: 005_add_app_plugins
Create Date: 2026-02-13

Tracks portable applications found on C: and D: drives.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '006_add_portable_apps'
down_revision = '005_add_app_plugins'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'portable_applications',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('agent_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('version', sa.String(100), nullable=True),
        sa.Column('executable_path', sa.String(500), nullable=True),
        sa.Column('install_directory', sa.String(500), nullable=True),
        sa.Column('publisher', sa.String(255), nullable=True),
        sa.Column('detection_method', sa.String(50), nullable=True),
        sa.Column('file_size_bytes', sa.BigInteger(), nullable=True),
        sa.Column('first_detected', sa.DateTime(), nullable=True),
        sa.Column('last_updated', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.agent_id'], ondelete='CASCADE'),
        sa.UniqueConstraint('agent_id', 'executable_path', name='uq_portable_app_agent_path')
    )
    op.create_index('ix_portable_applications_agent_id', 'portable_applications', ['agent_id'])
    print("[MIGRATION] Created portable_applications table")


def downgrade():
    op.drop_index('ix_portable_applications_agent_id', table_name='portable_applications')
    op.drop_table('portable_applications')
    print("[MIGRATION] Dropped portable_applications table")
