"""Add unique constraint for agent registration TOCTOU fix

Revision ID: 20260618_agent_unique
Revises: 20260506_missing_cols
Create Date: 2026-06-18

C-07 FIX: Prevents TOCTOU race condition in parallel agent registration
by adding a unique constraint on (agent_id, hostname) combination.
"""
from alembic import op
import sqlalchemy as sa

revision = '20260618_agent_unique'
down_revision = '20260506_missing_cols'
branch_labels = None
depends_on = None


def upgrade():
    # Add unique constraint on (agent_id, hostname)
    # This prevents duplicate registrations from parallel requests
    op.create_unique_constraint(
        'uq_agents_agent_id_hostname',
        'agents',
        ['agent_id', 'hostname']
    )


def downgrade():
    # Remove the unique constraint
    op.drop_constraint(
        'uq_agents_agent_id_hostname',
        'agents',
        type_='unique'
    )
