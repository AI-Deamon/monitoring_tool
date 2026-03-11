"""Merge multiple head branches for session_version addition

Revision ID: 12b58bbde69e
Revises: 004_session_version, 20260303_auto_update, 931a3b58e3bc
Create Date: 2026-03-04 17:00:52.800019

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '12b58bbde69e'
down_revision: Union[str, Sequence[str], None] = ('004_session_version', '20260303_auto_update', '931a3b58e3bc')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
