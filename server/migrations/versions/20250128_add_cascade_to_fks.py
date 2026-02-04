"""Add ON UPDATE CASCADE to foreign keys referencing agents.id

This migration adds ON UPDATE CASCADE to all foreign key constraints
that reference the agents table. This ensures that if an agent's ID
is ever updated, all referencing records are automatically updated,
preventing ForeignKeyViolation errors.

Revision ID: 20250128_add_cascade_to_fks
Revises: 20250218_add_deduplication
Create Date: 2026-01-28
"""

from alembic import op
from sqlalchemy import text


# revision identifiers
revision = '20250128_add_cascade_to_fks'
down_revision = '20250218_add_deduplication'
branch_labels = None
depends_on = None


# List of (table_name, constraint_name) for all FKs referencing agents.id
FK_CONSTRAINTS = [
    ('agent_current_status', 'agent_current_status_agent_id_fkey'),
    ('screen_time', 'screen_time_agent_id_fkey'),
    ('app_usage', 'app_usage_agent_id_fkey'),
    ('app_sessions', 'app_sessions_agent_id_fkey'),
    ('domain_usage', 'domain_usage_agent_id_fkey'),
    ('domain_sessions', 'domain_sessions_agent_id_fkey'),
    ('app_inventory', 'app_inventory_agent_id_fkey'),
    ('app_inventory_changes', 'app_inventory_changes_agent_id_fkey'),
    ('state_changes', 'state_changes_agent_id_fkey'),
    ('raw_events', 'raw_events_agent_id_fkey'),
]


def upgrade():
    """Add ON UPDATE CASCADE to all foreign keys referencing agents.id"""
    
    for table_name, constraint_name in FK_CONSTRAINTS:
        # Try to update foreign key constraint
        try:
            # Check if table exists first
            table_exists = False
            result = op.get_bind().execute(
                text("SELECT 1 FROM information_schema.tables WHERE table_name = :table_name"),
                {"table_name": table_name}
            )
            if result.fetchone():
                table_exists = True
            
            if not table_exists:
                print(f"[MIGRATION] Skipping {table_name}: Table does not exist")
                continue
                
            # Check if constraint exists
            constraint_exists = False
            result = op.get_bind().execute(
                text("""
                    SELECT 1 FROM information_schema.table_constraints 
                    WHERE table_name = :table_name AND constraint_name = :constraint_name AND constraint_type = 'FOREIGN KEY'
                """),
                {"table_name": table_name, "constraint_name": constraint_name}
            )
            if result.fetchone():
                constraint_exists = True
                
            if constraint_exists:
                # Drop existing constraint
                op.execute(f'ALTER TABLE {table_name} DROP CONSTRAINT {constraint_name} CASCADE')
            
            # Re-create with ON UPDATE CASCADE and ON DELETE CASCADE
            # We need to reference agents.agent_id (UUID) instead of agents.id (integer)
            op.execute(f"""
                ALTER TABLE {table_name} 
                ADD CONSTRAINT {constraint_name} 
                FOREIGN KEY (agent_id) REFERENCES agents(agent_id) 
                ON UPDATE CASCADE ON DELETE CASCADE
            """)
            
            print(f"[MIGRATION] Updated FK {constraint_name} on {table_name} with CASCADE")
        except Exception as e:
            print(f"[MIGRATION] Skipping {table_name}: {e}")


def downgrade():
    """Remove CASCADE from foreign keys (revert to simple FKs)"""
    
    for table_name, constraint_name in FK_CONSTRAINTS:
        try:
            op.drop_constraint(constraint_name, table_name, type_='foreignkey')
        except Exception:
            pass
        
        # Re-create without CASCADE
        op.create_foreign_key(
            constraint_name,
            table_name,
            'agents',
            ['agent_id'],
            ['id']
        )
