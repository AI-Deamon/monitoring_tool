"""merge heads

Revision ID: 1eb7f9e3f23e
Revises: 20260403_fix_screentime, ddf577c0e871
Create Date: 2026-04-03 12:08:13.248625

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1eb7f9e3f23e'
down_revision: Union[str, Sequence[str], None] = ('20260403_fix_screentime', 'ddf577c0e871')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
