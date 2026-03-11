"""add_security_indicators

Revision ID: a7e3b9c12d45
Revises: d20081a6c299
Create Date: 2026-02-17 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a7e3b9c12d45'
down_revision: Union[str, Sequence[str], None] = 'd20081a6c299'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create security_indicators table."""
    op.create_table('security_indicators',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('agent_id', sa.UUID(), nullable=False),
        sa.Column('indicator_type', sa.String(length=50), nullable=False),
        sa.Column('severity', sa.String(length=20), nullable=False),
        sa.Column('title', sa.String(length=500), nullable=False),
        sa.Column('details_json', sa.Text(), nullable=True),
        sa.Column('risk_score', sa.Integer(), server_default='0'),
        sa.Column('first_detected', sa.DateTime(), nullable=True),
        sa.Column('last_seen', sa.DateTime(), nullable=True),
        sa.Column('resolved', sa.Boolean(), server_default='false'),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.agent_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('agent_id', 'indicator_type', 'title', name='uq_security_agent_type_title'),
    )
    op.create_index(
        op.f('ix_security_indicators_agent_id'),
        'security_indicators', ['agent_id'], unique=False
    )


def downgrade() -> None:
    """Drop security_indicators table."""
    op.drop_index(op.f('ix_security_indicators_agent_id'), table_name='security_indicators')
    op.drop_table('security_indicators')
