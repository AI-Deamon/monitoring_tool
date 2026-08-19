"""create core aggregation tables

Revision ID: 003a_create_core_tables
Revises: 002_add_new_tables
Create Date: 2026-02-03

This migration creates all the core aggregation tables that were previously
created by db.create_all() or manual SQL scripts.

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '003a_create_core_tables'
down_revision = '002_add_new_tables'
branch_labels = None
depends_on = None


def upgrade():
    """Create all core aggregation tables."""
    
    # Create screen_time table
    op.create_table('screen_time',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('agent_id', sa.String(length=128), nullable=False),
        sa.Column('username', sa.String(length=255), nullable=True),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('active_seconds', sa.Float(), server_default='0', nullable=True),
        sa.Column('idle_seconds', sa.Float(), server_default='0', nullable=True),
        sa.Column('locked_seconds', sa.Float(), server_default='0', nullable=True),
        sa.Column('away_seconds', sa.Float(), server_default='0', nullable=True),
        sa.Column('last_updated', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.agent_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('agent_id', 'date', name='uq_screen_time_agent_date')
    )
    op.create_index('ix_screen_time_agent_id', 'screen_time', ['agent_id'], unique=False)
    
    # Create app_usage table
    op.create_table('app_usage',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('agent_id', sa.String(length=128), nullable=False),
        sa.Column('username', sa.String(length=255), nullable=True),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('app', sa.String(length=255), nullable=False),
        sa.Column('duration_seconds', sa.Integer(), server_default='0', nullable=True),
        sa.Column('session_count', sa.Integer(), server_default='0', nullable=True),
        sa.Column('last_updated', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.agent_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('agent_id', 'date', 'app', name='uq_app_usage_agent_date_app')
    )
    op.create_index('ix_app_usage_agent_id', 'app_usage', ['agent_id'], unique=False)
    
    # Create domain_usage table
    op.create_table('domain_usage',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('agent_id', sa.String(length=128), nullable=False),
        sa.Column('username', sa.String(length=255), nullable=True),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('domain', sa.String(length=255), nullable=False),
        sa.Column('browser', sa.String(length=50), nullable=True),
        sa.Column('duration_seconds', sa.Integer(), server_default='0', nullable=True),
        sa.Column('session_count', sa.Integer(), server_default='0', nullable=True),
        sa.Column('last_updated', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.agent_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('agent_id', 'date', 'domain', name='uq_domain_usage_agent_date_domain')
    )
    op.create_index('ix_domain_usage_agent_id', 'domain_usage', ['agent_id'], unique=False)
    
    # Create domain_sessions table
    op.create_table('domain_sessions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('agent_id', sa.String(length=128), nullable=False),
        sa.Column('username', sa.String(length=255), nullable=True),
        sa.Column('domain', sa.String(length=255), nullable=False),
        sa.Column('browser', sa.String(length=50), nullable=True),
        sa.Column('url', sa.Text(), nullable=True),
        sa.Column('start_time', sa.DateTime(), nullable=False),
        sa.Column('end_time', sa.DateTime(), nullable=True),
        sa.Column('duration_seconds', sa.Float(), server_default='0', nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('raw_title', sa.Text(), nullable=True),
        sa.Column('raw_url', sa.Text(), nullable=True),
        sa.Column('domain_source', sa.String(length=20), server_default='agent', nullable=True),
        sa.Column('needs_review', sa.Boolean(), server_default='false', nullable=True),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.agent_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_domain_sessions_agent_id', 'domain_sessions', ['agent_id'], unique=False)
    
    # Create app_inventory table
    op.create_table('app_inventory',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('agent_id', sa.String(length=128), nullable=False),
        sa.Column('name', sa.String(length=512), nullable=False),
        sa.Column('version', sa.String(length=128), nullable=True),
        sa.Column('publisher', sa.String(length=512), nullable=True),
        sa.Column('install_date', sa.Date(), nullable=True),
        sa.Column('install_location', sa.Text(), nullable=True),
        sa.Column('uninstall_string', sa.Text(), nullable=True),
        sa.Column('discovered_at', sa.DateTime(), nullable=True),
        sa.Column('last_seen', sa.DateTime(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=True),
        sa.Column('source', sa.String(length=50), nullable=True),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.agent_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_app_inventory_agent_id', 'app_inventory', ['agent_id'], unique=False)
    op.create_index('ix_app_inventory_name', 'app_inventory', ['name'], unique=False)
    
    # Create agent_current_status table
    op.create_table('agent_current_status',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('agent_id', sa.String(length=128), nullable=False),
        sa.Column('username', sa.String(length=255), nullable=True),
        sa.Column('current_app', sa.String(length=255), nullable=True),
        sa.Column('window_title', sa.Text(), nullable=True),
        sa.Column('current_domain', sa.String(length=255), nullable=True),
        sa.Column('current_browser', sa.String(length=50), nullable=True),
        sa.Column('current_url', sa.Text(), nullable=True),
        sa.Column('current_state', sa.String(length=20), nullable=True),
        sa.Column('session_start', sa.DateTime(), nullable=True),
        sa.Column('duration_seconds', sa.Integer(), server_default='0', nullable=True),
        sa.Column('domain_session_start', sa.DateTime(), nullable=True),
        sa.Column('domain_duration_seconds', sa.Integer(), server_default='0', nullable=True),
        sa.Column('last_seen', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.agent_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('agent_id', name='uq_agent_current_status_agent_id')
    )
    op.create_index('ix_agent_current_status_agent_id', 'agent_current_status', ['agent_id'], unique=False)
    
    # Create raw_events table
    op.create_table('raw_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('agent_id', sa.String(length=128), nullable=False),
        sa.Column('event_type', sa.String(length=50), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=True),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('received_at', sa.DateTime(), nullable=False),
        sa.Column('processed', sa.Boolean(), server_default='false', nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.agent_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_raw_events_agent_id', 'raw_events', ['agent_id'], unique=False)
    op.create_index('ix_raw_events_processed', 'raw_events', ['processed'], unique=False)
    
    # Create telemetry_events table
    op.create_table('telemetry_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('agent_id', sa.String(length=128), nullable=False),
        sa.Column('event_type', sa.String(length=50), nullable=False),
        sa.Column('event_data', sa.JSON(), nullable=True),
        sa.Column('timestamp', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.agent_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_telemetry_events_agent_id', 'telemetry_events', ['agent_id'], unique=False)
    op.create_index('ix_telemetry_events_timestamp', 'telemetry_events', ['timestamp'], unique=False)
    
    # Create screen_time_spans table
    op.create_table('screen_time_spans',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('span_id', sa.String(length=128), nullable=False),
        sa.Column('agent_id', sa.String(length=128), nullable=False),
        sa.Column('state', sa.String(length=20), nullable=False),
        sa.Column('start_time', sa.DateTime(), nullable=False),
        sa.Column('end_time', sa.DateTime(), nullable=False),
        sa.Column('duration_seconds', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('processed', sa.Boolean(), server_default='false', nullable=True),
        sa.CheckConstraint("state IN ('active', 'idle', 'locked')", name='check_screen_time_spans_state'),
        sa.CheckConstraint('duration_seconds > 0 AND duration_seconds <= 86400', name='check_screen_time_spans_duration'),
        sa.CheckConstraint('end_time > start_time', name='check_screen_time_spans_time_range'),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.agent_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('span_id', name='uq_screen_time_spans_span_id')
    )
    op.create_index('ix_screen_time_spans_agent_id', 'screen_time_spans', ['agent_id'], unique=False)
    op.create_index('ix_screen_time_spans_span_id', 'screen_time_spans', ['span_id'], unique=False)
    op.create_index('ix_screen_time_spans_processed', 'screen_time_spans', ['processed'], unique=False)
    
    print("Core aggregation tables created successfully!")


def downgrade():
    """Drop all core aggregation tables."""
    op.drop_table('screen_time_spans')
    op.drop_table('telemetry_events')
    op.drop_table('raw_events')
    op.drop_table('agent_current_status')
    op.drop_table('app_inventory')
    op.drop_table('domain_sessions')
    op.drop_table('domain_usage')
    op.drop_table('app_usage')
    op.drop_table('screen_time')
    print("[OK] Core aggregation tables dropped")
