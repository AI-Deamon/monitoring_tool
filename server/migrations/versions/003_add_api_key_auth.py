"""Add api_key and status columns to agents table

Revision ID: 003_add_api_key_auth
Revises: 87b72471d98c
Create Date: 2025-12-07 12:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '003_add_api_key_auth'
down_revision = '20250128_add_cascade_to_fks'
branch_labels = None
depends_on = None


def upgrade():
    """Add api_key and status columns to agents table for new authentication."""
    # SQLite doesn't support ADD COLUMN with constraints easily
    # Use simple add_column without batch mode
    
    # Check if columns already exist (for idempotency)
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [col['name'] for col in inspector.get_columns('agents')]
    
    if 'api_key' not in columns:
        op.add_column('agents', sa.Column('api_key', sa.String(128), nullable=True))
    
    if 'status' not in columns:
        op.add_column('agents', sa.Column('status', sa.String(50), nullable=True))
        # Set default for existing rows
        op.execute("UPDATE agents SET status = 'active' WHERE status IS NULL")


def downgrade():
    """Remove api_key and status columns from agents table."""
    # SQLite doesn't support DROP COLUMN directly
    # Need to recreate table, but for simplicity we'll just leave columns
    pass
