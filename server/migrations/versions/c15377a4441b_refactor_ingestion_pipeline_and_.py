"""Refactor ingestion pipeline and database schema

Revision ID: c15377a4441b
Revises: 002_add_new_tables
Create Date: 2025-12-04 16:13:11.981953

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import table, column
import uuid
import hashlib
import secrets
from datetime import datetime
from dateutil.parser import parse as parse_date

# revision identifiers, used by Alembic.
revision: str = 'c15377a4441b'
down_revision: Union[str, Sequence[str], None] = '002_add_new_tables'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    Session = sessionmaker(bind=bind)
    session = Session()

    # Drop all foreign keys pointing to agents.agent_id
    op.drop_constraint('heartbeats_agent_id_fkey', 'heartbeats', type_='foreignkey')
    try:
        op.drop_constraint('events_agent_id_fkey', 'events', type_='foreignkey')
    except Exception:
        pass # may not exist
    try:
        op.drop_constraint('applications_agent_id_fkey', 'applications', type_='foreignkey')
    except Exception:
        pass
    try:
        op.drop_constraint('app_inventory_changes_agent_id_fkey', 'app_inventory_changes', type_='foreignkey')
    except Exception:
        pass
    try:
        op.drop_constraint('screen_time_logs_agent_id_fkey', 'screen_time_logs', type_='foreignkey')
    except Exception:
        pass
    try:
        op.drop_constraint('app_usage_logs_agent_id_fkey', 'app_usage_logs', type_='foreignkey')
    except Exception:
        pass
    try:
        op.drop_constraint('domain_usage_logs_agent_id_fkey', 'domain_usage_logs', type_='foreignkey')
    except Exception:
        pass
    try:
        op.drop_constraint('domain_visits_agent_id_fkey', 'domain_visits', type_='foreignkey')
    except Exception:
        pass
    try:
        op.drop_constraint('process_sessions_agent_id_fkey', 'process_sessions', type_='foreignkey')
    except Exception:
        pass
    try:
        op.drop_constraint('merged_event_logs_agent_id_fkey', 'merged_event_logs', type_='foreignkey')
    except Exception:
        pass
    try:
        op.drop_constraint('batch_deduplication_agent_id_fkey', 'batch_deduplication', type_='foreignkey')
    except Exception:
        pass


    # ### Schema changes ###
    op.create_table('app_sessions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('agent_id', UUID(as_uuid=True), nullable=False),
        sa.Column('app_name', sa.Text(), nullable=False),
        sa.Column('start', sa.DateTime(), nullable=False),
        sa.Column('end', sa.DateTime(), nullable=False),
        sa.Column('duration_seconds', sa.Integer(), nullable=False),
        sa.Column('window_title', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_app_sessions_agent_id'), 'app_sessions', ['agent_id'], unique=False)

    op.create_table('idle_sessions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('agent_id', UUID(as_uuid=True), nullable=False),
        sa.Column('state', sa.String(length=10), nullable=False),
        sa.Column('start', sa.DateTime(), nullable=False),
        sa.Column('end', sa.DateTime(), nullable=False),
        sa.Column('duration_seconds', sa.Integer(), nullable=False),
        sa.CheckConstraint("state IN ('active', 'idle', 'locked')"),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_idle_sessions_agent_id'), 'idle_sessions', ['agent_id'], unique=False)

    op.create_table('inventory_snapshots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('agent_id', UUID(as_uuid=True), nullable=False),
        sa.Column('apps', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_inventory_snapshots_agent_id'), 'inventory_snapshots', ['agent_id'], unique=False)

    # Alter agents table
    op.add_column('agents', sa.Column('registration_timestamp', sa.DateTime(), nullable=True))
    op.add_column('agents', sa.Column('policy_version', sa.Integer(), server_default='1', nullable=True))
    op.add_column('agents', sa.Column('config_version', sa.Integer(), server_default='1', nullable=True))

    # Generate new api keys for existing agents
    agents_table = table('agents',
        column('id', sa.Integer),
        column('agent_id', sa.String),
        column('hashed_api_token', sa.String)
    )
    agents = session.execute(sa.select(agents_table)).fetchall()
    for agent in agents:
        api_token = secrets.token_urlsafe(32)
        api_token_hash = hashlib.sha256(api_token.encode()).hexdigest()
        session.execute(
            agents_table.update().where(agents_table.c.id == agent.id).values(
                hashed_api_token=api_token_hash,
            )
        )
    session.commit()
    
    op.alter_column('agents', 'agent_id',
               existing_type=sa.VARCHAR(length=128),
               type_=UUID(as_uuid=True),
               postgresql_using='agent_id::uuid',
               nullable=False)

    op.alter_column('agents', 'hashed_api_token',
               existing_type=sa.VARCHAR(length=128),
               nullable=False, unique=True)
    
    op.create_foreign_key('fk_app_sessions_agent_id', 'app_sessions', 'agents', ['agent_id'], ['agent_id'], ondelete='CASCADE')
    op.create_foreign_key('fk_idle_sessions_agent_id', 'idle_sessions', 'agents', ['agent_id'], ['agent_id'], ondelete='CASCADE')
    op.create_foreign_key('fk_inventory_snapshots_agent_id', 'inventory_snapshots', 'agents', ['agent_id'], ['agent_id'], ondelete='CASCADE')
    
    # Alter domain_active_sessions table
    op.alter_column('domain_active_sessions', 'agent_id',
               existing_type=sa.VARCHAR(length=128),
               type_=UUID(as_uuid=True),
               postgresql_using='agent_id::uuid',
               nullable=False)
    op.alter_column('domain_active_sessions', 'domain',
               existing_type=sa.VARCHAR(length=512),
               type_=sa.Text(),
               nullable=False)
    op.alter_column('domain_active_sessions', 'browser',
               existing_type=sa.VARCHAR(length=128),
               type_=sa.Text(),
               nullable=True)
    op.create_foreign_key('fk_domain_active_sessions_agent_id', 'domain_active_sessions', 'agents', ['agent_id'], ['agent_id'], ondelete='CASCADE')

    # Alter heartbeats table
    op.alter_column('heartbeats', 'agent_id',
               existing_type=sa.VARCHAR(length=128),
               type_=UUID(as_uuid=True),
               postgresql_using='agent_id::uuid',
               nullable=False)
    op.add_column('heartbeats', sa.Column('state', sa.String(10)))
    op.add_column('heartbeats', sa.Column('active_app', sa.Text))
    op.create_foreign_key('fk_heartbeats_agent_id', 'heartbeats', 'agents', ['agent_id'], ['agent_id'], ondelete='CASCADE')

    # Alter merged_event_logs table
    op.alter_column('merged_event_logs', 'agent_id',
                existing_type=sa.VARCHAR(length=128),
                type_=UUID(as_uuid=True),
                postgresql_using='agent_id::uuid',
                nullable=False)
    op.create_foreign_key('fk_merged_event_logs_agent_id', 'merged_event_logs', 'agents', ['agent_id'], ['agent_id'], ondelete='CASCADE')


    # Data Migration
    merged_events_table = table('merged_event_logs',
        column('agent_id', UUID),
        column('data', sa.JSON)
    )
    app_sessions_table = table('app_sessions',
        column('agent_id', UUID),
        column('app_name', sa.Text),
        column('start', sa.DateTime),
        column('end', sa.DateTime),
        column('duration_seconds', sa.Integer),
        column('window_title', sa.Text)
    )
    idle_sessions_table = table('idle_sessions',
        column('agent_id', UUID),
        column('state', sa.String),
        column('start', sa.DateTime),
        column('end', sa.DateTime),
        column('duration_seconds', sa.Integer),
    )

    merged_events = session.execute(sa.select(merged_events_table)).fetchall()
    for event in merged_events:
        if not event.data or 'events' not in event.data:
            continue
        for sub_event in event.data['events']:
            try:
                agent_uuid = event.agent_id
                start_time = parse_date(sub_event['start'])
                end_time = parse_date(sub_event['end'])
                duration = int(sub_event['duration_seconds'])
                state_obj = sub_event.get('state', {})

                if sub_event.get('type') == 'app':
                    op.bulk_insert(app_sessions_table, [{
                        'agent_id': agent_uuid,
                        'app_name': state_obj.get('app_name'),
                        'start': start_time,
                        'end': end_time,
                        'duration_seconds': duration,
                        'window_title': state_obj.get('window_title')
                    }])
                elif sub_event.get('type') == 'idle':
                    op.bulk_insert(idle_sessions_table, [{
                        'agent_id': agent_uuid,
                        'state': state_obj.get('state'),
                        'start': start_time,
                        'end': end_time,
                        'duration_seconds': duration,
                    }])
            except (ValueError, TypeError, KeyError) as e:
                print(f"Skipping malformed sub_event: {sub_event}. Error: {e}")

    # Drop old tables
    op.drop_table('app_inventory_changes')
    op.drop_table('process_sessions')
    op.drop_table('batch_deduplication')
    op.drop_table('domain_usage_logs')
    op.drop_table('app_usage_logs')
    op.drop_table('screen_time_logs')
    op.drop_table('domain_visits')
    op.drop_table('applications')
    op.drop_table('file_uploads')
    op.drop_table('events')

    session.commit()


def downgrade() -> None:
    """Downgrade schema."""
    # This is a destructive downgrade. Data will be lost.
    op.create_table('events',
        sa.Column('id', sa.INTEGER(), autoincrement=True, nullable=False),
        sa.Column('agent_id', sa.VARCHAR(length=128), autoincrement=False, nullable=True),
        sa.Column('event_type', sa.VARCHAR(length=128), autoincrement=False, nullable=True),
        sa.Column('payload', sa.JSON(), autoincrement=False, nullable=True),
        sa.Column('created_at', sa.DateTime(), autoincrement=False, nullable=True),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.agent_id'], name='events_agent_id_fkey'),
        sa.PrimaryKeyConstraint('id', name='events_pkey')
    )
    # Recreate other tables if necessary for a full downgrade. For this refactor, we assume a one-way migration.
    
    op.drop_table('inventory_snapshots')
    op.drop_table('idle_sessions')
    op.drop_table('app_sessions')

    op.drop_column('agents', 'registration_timestamp')
    op.drop_column('agents', 'policy_version')
    op.drop_column('agents', 'config_version')
    op.alter_column('agents', 'agent_id',
               existing_type=UUID(as_uuid=True),
               type_=sa.VARCHAR(length=128),
               nullable=False)
    op.alter_column('agents', 'hashed_api_token',
               existing_type=sa.VARCHAR(length=128),
               nullable=True)
    op.drop_constraint('agents_hashed_api_token_key', 'agents', type_='unique')
    
    op.drop_constraint('fk_domain_active_sessions_agent_id', 'domain_active_sessions', type_='foreignkey')
    op.drop_constraint('fk_heartbeats_agent_id', 'heartbeats', type_='foreignkey')
    op.drop_constraint('fk_merged_event_logs_agent_id', 'merged_event_logs', type_='foreignkey')

    op.alter_column('heartbeats', 'agent_id',
               existing_type=UUID(as_uuid=True),
               type_=sa.VARCHAR(length=128),
               nullable=True)
    op.drop_column('heartbeats', 'state')
    op.drop_column('heartbeats', 'active_app')

    op.alter_column('domain_active_sessions', 'agent_id',
               existing_type=UUID(as_uuid=True),
               type_=sa.VARCHAR(length=128),
               nullable=True)
    op.alter_column('domain_active_sessions', 'domain',
               existing_type=sa.Text(),
               type_=sa.VARCHAR(512),
               nullable=True)
    op.alter_column('domain_active_sessions', 'browser',
               existing_type=sa.Text(),
               type_=sa.VARCHAR(128),
               nullable=True)
               
    op.alter_column('merged_event_logs', 'agent_id',
                existing_type=UUID(as_uuid=True),
                type_=sa.VARCHAR(length=128),
                nullable=True)
               
    op.create_foreign_key('heartbeats_agent_id_fkey', 'heartbeats', 'agents', ['agent_id'], ['agent_id'])
    op.create_foreign_key('events_agent_id_fkey', 'events', 'agents', ['agent_id'], ['agent_id'])