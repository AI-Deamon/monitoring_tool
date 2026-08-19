"""add asset_info.bios_version (feature 037, D06 / FR-015)

The agent's hardware collector already queries SMBIOSBIOSVersion, but the value
was never parsed, never stored, and never served — there was no column to put it
in. The dashboard's "BIOS Version" field was a static placeholder, and the API
served bios_uuid (a hardware GUID) instead, which is what QA saw as a "wrong
BIOS version".

This adds the missing column. Distinct from the existing bios_uuid column:
bios_uuid is an identifier, bios_version is a firmware version string.

Revision ID: 20260807_add_bios_version
Revises: 20260806_screen_time_span_auth
Create Date: 2026-08-07
"""
import sqlalchemy as sa
from alembic import op

revision = '20260807_add_bios_version'
down_revision = '20260806_screen_time_span_auth'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'asset_info',
        sa.Column('bios_version', sa.String(length=255), nullable=True),
    )


def downgrade():
    op.drop_column('asset_info', 'bios_version')
