"""fix_agents_id_to_string

Revision ID: b416dc8ef37f
Revises: 003_add_api_key_auth
Create Date: 2025-12-07 12:37:48.019372

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b416dc8ef37f'
down_revision: Union[str, Sequence[str], None] = '003_add_api_key_auth'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Update agents.id from integer to varchar
    op.execute('ALTER TABLE agents DROP CONSTRAINT agents_pkey')
    op.execute('ALTER TABLE agents ADD COLUMN temp_id VARCHAR(128)')
    op.execute('UPDATE agents SET temp_id = id::text')
    op.execute('ALTER TABLE agents DROP COLUMN id')
    op.execute('ALTER TABLE agents RENAME COLUMN temp_id TO id')
    op.execute('ALTER TABLE agents ADD PRIMARY KEY (id)')


def downgrade() -> None:
    """Downgrade schema."""
    # Revert back to integer id
    op.execute('ALTER TABLE agents DROP CONSTRAINT agents_pkey')
    op.execute('ALTER TABLE agents ADD COLUMN temp_id INTEGER')
    op.execute('UPDATE agents SET temp_id = id::integer')
    op.execute('ALTER TABLE agents DROP COLUMN id')
    op.execute('ALTER TABLE agents RENAME COLUMN temp_id TO id')
    op.execute('ALTER TABLE agents ADD PRIMARY KEY (id)')
