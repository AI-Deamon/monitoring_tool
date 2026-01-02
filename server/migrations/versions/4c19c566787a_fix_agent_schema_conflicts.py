"""fix_agent_schema_conflicts

Revision ID: 4c19c566787a
Revises: b416dc8ef37f
Create Date: 2025-12-07 12:40:29.920070

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4c19c566787a'
down_revision: Union[str, Sequence[str], None] = 'b416dc8ef37f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Drop foreign key constraints that reference agent_id
    op.execute('ALTER TABLE app_sessions DROP CONSTRAINT fk_app_sessions_agent_id')
    op.execute('ALTER TABLE idle_sessions DROP CONSTRAINT fk_idle_sessions_agent_id')
    op.execute('ALTER TABLE inventory_snapshots DROP CONSTRAINT fk_inventory_snapshots_agent_id')
    op.execute('ALTER TABLE domain_active_sessions DROP CONSTRAINT fk_domain_active_sessions_agent_id')
    op.execute('ALTER TABLE heartbeats DROP CONSTRAINT fk_heartbeats_agent_id')
    op.execute('ALTER TABLE merged_event_logs DROP CONSTRAINT fk_merged_event_logs_agent_id')
    
    # Drop agent_id column
    op.execute('ALTER TABLE agents DROP COLUMN agent_id')


def downgrade() -> None:
    """Downgrade schema."""
    # Add back agent_id column
    op.execute('ALTER TABLE agents ADD COLUMN agent_id UUID NOT NULL DEFAULT gen_random_uuid()')
    
    # Recreate foreign key constraints
    op.execute('ALTER TABLE app_sessions ADD CONSTRAINT fk_app_sessions_agent_id FOREIGN KEY (agent_id) REFERENCES agents(agent_id)')
    op.execute('ALTER TABLE idle_sessions ADD CONSTRAINT fk_idle_sessions_agent_id FOREIGN KEY (agent_id) REFERENCES agents(agent_id)')
    op.execute('ALTER TABLE inventory_snapshots ADD CONSTRAINT fk_inventory_snapshots_agent_id FOREIGN KEY (agent_id) REFERENCES agents(agent_id)')
    op.execute('ALTER TABLE domain_active_sessions ADD CONSTRAINT fk_domain_active_sessions_agent_id FOREIGN KEY (agent_id) REFERENCES agents(agent_id)')
    op.execute('ALTER TABLE heartbeats ADD CONSTRAINT fk_heartbeats_agent_id FOREIGN KEY (agent_id) REFERENCES agents(agent_id)')
    op.execute('ALTER TABLE merged_event_logs ADD CONSTRAINT fk_merged_event_logs_agent_id FOREIGN KEY (agent_id) REFERENCES agents(agent_id)')
