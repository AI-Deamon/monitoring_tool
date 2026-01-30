"""merge_heads

Revision ID: 68e2644c1171
Revises: 006_add_domain_visits, 20250128_add_cascade_to_fks, 20250218_add_domain_duration, add_screentime_spans
Create Date: 2026-01-29 16:48:30.919633

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '68e2644c1171'
down_revision: Union[str, Sequence[str], None] = ('006_add_domain_visits', '20250128_add_cascade_to_fks', '20250218_add_domain_duration', 'add_screentime_spans')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
