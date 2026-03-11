"""Add foreign key cascades for agent deletion manual

Revision ID: 0c9e87d78584
Revises: 20260218_session_reset
Create Date: 2026-02-18 15:53:00

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0c9e87d78584'
down_revision: Union[str, Sequence[str], None] = '20260218_session_reset'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES_WITH_AGENT_FK = [
    'agent_current_status', 'screen_time', 'app_usage', 'app_sessions',
    'domain_usage', 'domain_sessions', 'app_inventory', 'app_inventory_changes',
    'state_changes', 'domain_visits', 'raw_events', 'asset_info'
]

def upgrade() -> None:
    # Drop existing foreign keys and recreate with ON DELETE CASCADE
    for table in TABLES_WITH_AGENT_FK:
        # We use a try-except block in raw SQL to handle cases where constraint names might differ
        # or if CASCADE is already present (unlikely given the bug report)
        constraint_name = f"{table}_agent_id_fkey"
        
        # PostgreSQL specific syntax for dropping if exists and adding
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {constraint_name}")
        op.create_foreign_key(
            constraint_name,
            table, 'agents',
            ['agent_id'], ['agent_id'],
            ondelete='CASCADE'
        )

def downgrade() -> None:
    for table in TABLES_WITH_AGENT_FK:
        constraint_name = f"{table}_agent_id_fkey"
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {constraint_name}")
        op.create_foreign_key(
            constraint_name,
            table, 'agents',
            ['agent_id'], ['agent_id']
        )
