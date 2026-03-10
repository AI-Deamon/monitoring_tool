"""enterprise_assets_upgrade

Revision ID: df29e57c74bb
Revises: c7c09b33cce8
Create Date: 2026-02-12 16:45:36.358507

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'df29e57c74bb'
down_revision: Union[str, Sequence[str], None] = 'c7c09b33cce8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Create Organizations table if not exists (using manual SQL for safety since it might exist)
    op.execute('CREATE TABLE IF NOT EXISTS organizations ('
               'id SERIAL PRIMARY KEY, '
               'org_id UUID UNIQUE NOT NULL DEFAULT gen_random_uuid(), '
               'name VARCHAR(255) NOT NULL, '
               'slug VARCHAR(100) UNIQUE NOT NULL, '
               'created_at TIMESTAMP DEFAULT NOW())')

    # 2. Add org_id to existing tables if not exists
    # dashboard_users
    op.execute('ALTER TABLE dashboard_users ADD COLUMN IF NOT EXISTS org_id INTEGER REFERENCES organizations(id)')
    op.execute('CREATE INDEX IF NOT EXISTS idx_dashboard_users_org_id ON dashboard_users(org_id)')

    # agents
    op.execute('ALTER TABLE agents ADD COLUMN IF NOT EXISTS org_id INTEGER REFERENCES organizations(id)')
    op.execute('CREATE INDEX IF NOT EXISTS idx_agents_org_id ON agents(org_id)')

    # asset_info
    op.execute('ALTER TABLE asset_info ADD COLUMN IF NOT EXISTS org_id INTEGER REFERENCES organizations(id)')
    op.execute('CREATE INDEX IF NOT EXISTS idx_asset_info_org_id ON asset_info(org_id)')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('idx_asset_info_org_id'), table_name='asset_info')
    op.drop_column('asset_info', 'org_id')

    op.drop_index(op.f('idx_agents_org_id'), table_name='agents')
    op.drop_column('agents', 'org_id')

    op.drop_index(op.f('idx_dashboard_users_org_id'), table_name='dashboard_users')
    op.drop_column('dashboard_users', 'org_id')

    op.drop_table('organizations')
