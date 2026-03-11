"""Merge heads

Revision ID: 931a3b58e3bc
Revises: 0c9e87d78584, 20260227_password_reset
Create Date: 2026-02-27 12:53:48.044973

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '931a3b58e3bc'
down_revision: Union[str, Sequence[str], None] = ('0c9e87d78584', '20260227_password_reset')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
