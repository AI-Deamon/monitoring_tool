"""merge_fix_inventory_and_app_switch_fix

Revision ID: ddf577c0e871
Revises: fix_inventory_changes_20260313, 20260401_fix_dedup
Create Date: 2026-04-01 13:31:49.596472

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ddf577c0e871'
down_revision: Union[str, Sequence[str], None] = ('fix_inventory_changes_20260313', '20260401_fix_dedup')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
