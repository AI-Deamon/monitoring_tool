"""eol_scanning_tables

Revision ID: d20081a6c299
Revises: df29e57c74bb
Create Date: 2026-02-12 16:56:19.055035

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd20081a6c299'
down_revision: Union[str, Sequence[str], None] = 'df29e57c74bb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create EOL scanning tables."""
    # 1. Software Lifecycle knowledge base
    op.create_table('software_lifecycle',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('product_name', sa.String(length=255), nullable=False),
        sa.Column('cycle', sa.String(length=100), nullable=False),
        sa.Column('release_label', sa.String(length=255), nullable=True),
        sa.Column('release_date', sa.Date(), nullable=True),
        sa.Column('eol_date', sa.Date(), nullable=True),
        sa.Column('eos_date', sa.Date(), nullable=True),
        sa.Column('is_lts', sa.Boolean(), nullable=True),
        sa.Column('latest_version', sa.String(length=100), nullable=True),
        sa.Column('reference_url', sa.Text(), nullable=True),
        sa.Column('source', sa.String(length=50), nullable=True),
        sa.Column('synced_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('product_name', 'cycle', name='uq_lifecycle_product_cycle')
    )
    op.create_index(op.f('ix_software_lifecycle_product_name'), 'software_lifecycle', ['product_name'], unique=False)

    # 2. Cached per-agent lifecycle evaluation results
    op.create_table('asset_lifecycle_status',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('agent_id', sa.UUID(), nullable=False),
        sa.Column('product_name', sa.String(length=255), nullable=False),
        sa.Column('installed_version', sa.String(length=255), nullable=True),
        sa.Column('matched_cycle', sa.String(length=100), nullable=True),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('eol_date', sa.Date(), nullable=True),
        sa.Column('risk_score', sa.Integer(), nullable=True),
        sa.Column('severity', sa.String(length=20), nullable=True),
        sa.Column('evaluated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.agent_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('agent_id', 'product_name', name='uq_asset_lifecycle_agent_product')
    )
    op.create_index(op.f('ix_asset_lifecycle_status_agent_id'), 'asset_lifecycle_status', ['agent_id'], unique=False)


def downgrade() -> None:
    """Drop EOL scanning tables."""
    op.drop_index(op.f('ix_asset_lifecycle_status_agent_id'), table_name='asset_lifecycle_status')
    op.drop_table('asset_lifecycle_status')
    op.drop_index(op.f('ix_software_lifecycle_product_name'), table_name='software_lifecycle')
    op.drop_table('software_lifecycle')
