"""Add auto-update management tables

Revision ID: 20260303_auto_update_tables
Revises: 20260227_password_reset
Create Date: 2026-03-03 12:24:00.000000

Creates:
  - update_history: Audit trail for update lifecycle events
  - update_global_policy: Singleton global policy (seeded with defaults)
  - update_versions: Version metadata cache for dashboard discovery
  - agents.force_update_check: Boolean for server-triggered immediate check
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers
revision = '20260303_auto_update'
down_revision = '20260227_password_reset'
branch_labels = None
depends_on = None


def upgrade():
    # ------------------------------------------------------------------
    # 1. update_history — audit every update lifecycle event
    # ------------------------------------------------------------------
    op.create_table('update_history',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('agent_id', sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('agents.agent_id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('from_version', sa.String(50), nullable=True),
        sa.Column('to_version', sa.String(50), nullable=False),
        sa.Column('status', sa.String(30), nullable=False),
        sa.Column('started_at', sa.DateTime, nullable=True),
        sa.Column('completed_at', sa.DateTime, nullable=True),
        sa.Column('error_message', sa.Text, nullable=True),
        sa.Column('package_sha256', sa.String(64), nullable=True),
        sa.Column('created_at', sa.DateTime, server_default=text('CURRENT_TIMESTAMP')),

        sa.Index('ix_update_history_agent_id', 'agent_id'),
        sa.Index('ix_update_history_created_at', 'created_at'),
        sa.Index('ix_update_history_agent_created', 'agent_id', 'created_at'),
    )

    # ------------------------------------------------------------------
    # 2. update_global_policy — singleton global auto-update policy
    # ------------------------------------------------------------------
    op.create_table('update_global_policy',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('auto_update_enabled', sa.Boolean, default=False),
        sa.Column('channel', sa.String(20), server_default='stable'),
        sa.Column('min_version', sa.String(50), nullable=True),
        sa.Column('canary_percentage', sa.Integer, server_default='0'),
        sa.Column('update_window_enabled', sa.Boolean, default=False),
        sa.Column('update_window_start', sa.Time, nullable=True),
        sa.Column('update_window_end', sa.Time, nullable=True),
        sa.Column('update_window_tz', sa.String(50), server_default='UTC'),
        sa.Column('updated_by', sa.String(255), nullable=True),
        sa.Column('created_at', sa.DateTime, server_default=text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime, server_default=text('CURRENT_TIMESTAMP')),
    )

    # Seed default policy row
    op.execute(text("""
        INSERT INTO update_global_policy
            (id, auto_update_enabled, channel, canary_percentage, update_window_enabled, update_window_tz)
        VALUES
            (1, FALSE, 'stable', 0, FALSE, 'UTC')
    """))

    # ------------------------------------------------------------------
    # 3. update_versions — version metadata cache
    # ------------------------------------------------------------------
    op.create_table('update_versions',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('version', sa.String(50), unique=True, nullable=False),
        sa.Column('artifact_type', sa.String(30), server_default='exe_bundle'),
        sa.Column('package_size', sa.BigInteger, nullable=True),
        sa.Column('package_sha256', sa.String(64), nullable=True),
        sa.Column('min_agent_version', sa.String(50), nullable=True),
        sa.Column('mandatory', sa.Boolean, default=False),
        sa.Column('changelog', sa.Text, nullable=True),
        sa.Column('release_date', sa.DateTime, nullable=True),
        sa.Column('is_active', sa.Boolean, default=True),
        sa.Column('created_at', sa.DateTime, server_default=text('CURRENT_TIMESTAMP')),

        sa.Index('ix_update_versions_version', 'version'),
    )

    # ------------------------------------------------------------------
    # 4. Add force_update_check to agents
    # ------------------------------------------------------------------
    op.add_column('agents',
                  sa.Column('force_update_check', sa.Boolean, server_default='false'))


def downgrade():
    op.drop_column('agents', 'force_update_check')
    op.drop_table('update_versions')
    op.drop_table('update_global_policy')
    op.drop_table('update_history')
