"""create_live_telemetry_tables

Revision ID: 87b72471d98c
Revises: c15377a4441b
Create Date: 2025-12-05 10:53:50.056559

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '87b72471d98c'
down_revision: Union[str, Sequence[str], None] = 'c15377a4441b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
