"""align_procedure_signatures

Revision ID: 7204218e0a8e
Revises: 4c113c00dd0f
Create Date: 2026-02-03 19:50:16.634455

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7204218e0a8e'
down_revision: Union[str, Sequence[str], None] = '4c113c00dd0f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    
    # 1. Align process_screentime_event (6 params expected by server)
    op.execute("DROP FUNCTION IF EXISTS process_screentime_event(VARCHAR, DATE, VARCHAR, INTEGER, INTEGER, INTEGER, INTEGER) CASCADE;") # Incorrect 7-param version
    op.execute("DROP FUNCTION IF EXISTS process_screentime_event(VARCHAR, TIMESTAMP, INTEGER, INTEGER, INTEGER, VARCHAR) CASCADE;") # Legacy 6-param version
    op.execute("""
        CREATE OR REPLACE FUNCTION process_screentime_event(
            p_agent_id VARCHAR,
            p_timestamp TIMESTAMP,
            p_active_total INTEGER,
            p_idle_total INTEGER,
            p_locked_total INTEGER,
            p_state VARCHAR
        ) RETURNS TABLE(status text, message text) AS $$
        DECLARE
            v_date DATE;
        BEGIN
            v_date := p_timestamp::DATE;
            
            INSERT INTO screen_time (
                agent_id, date, active_seconds, idle_seconds, locked_seconds, last_updated
            ) VALUES (
                p_agent_id::UUID, v_date, p_active_total, p_idle_total, p_locked_total, NOW()
            )
            ON CONFLICT (agent_id, date) DO UPDATE SET
                active_seconds = GREATEST(screen_time.active_seconds, EXCLUDED.active_seconds),
                idle_seconds = GREATEST(screen_time.idle_seconds, EXCLUDED.idle_seconds),
                locked_seconds = GREATEST(screen_time.locked_seconds, EXCLUDED.locked_seconds),
                last_updated = NOW();
                
            RETURN QUERY SELECT 'success'::text, 'Screentime processed'::text;
        EXCEPTION WHEN OTHERS THEN
            RETURN QUERY SELECT 'error'::text, SQLERRM::text;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # 2. Align process_app_switch_event (9 params expected by server)
    # Note: 20260129 consolidation had 8 params (missing friendly_name and category, used username instead)
    op.execute("DROP FUNCTION IF EXISTS process_app_switch_event(VARCHAR, VARCHAR, VARCHAR, TEXT, TIMESTAMP, TIMESTAMP, INTEGER, VARCHAR) CASCADE;") # Consolidated 8-param version
    op.execute("DROP FUNCTION IF EXISTS process_app_switch_event(VARCHAR, TIMESTAMP, VARCHAR, VARCHAR, VARCHAR, VARCHAR, TIMESTAMP, TIMESTAMP, FLOAT) CASCADE;") # Cleanup legacy
    op.execute("""
        CREATE OR REPLACE FUNCTION process_app_switch_event(
            p_agent_id VARCHAR,
            p_timestamp TIMESTAMP,
            p_app VARCHAR,
            p_friendly_name VARCHAR,
            p_category VARCHAR,
            p_window_title VARCHAR,
            p_session_start TIMESTAMP,
            p_session_end TIMESTAMP,
            p_total_seconds FLOAT
        ) RETURNS TABLE(status text, message text) AS $$
        DECLARE
            v_date DATE;
        BEGIN
            v_date := p_session_start::DATE;
            
            INSERT INTO app_sessions (
                agent_id, app, window_title, start_time, end_time, duration_seconds, created_at
            ) VALUES (
                p_agent_id::UUID, p_app, p_window_title, p_session_start, p_session_end, p_total_seconds, NOW()
            );
            
            INSERT INTO app_usage (
                agent_id, date, app, duration_seconds, session_count, last_updated
            ) VALUES (
                p_agent_id::UUID, v_date, p_app, p_total_seconds::INTEGER, 1, NOW()
            )
            ON CONFLICT (agent_id, date, app) DO UPDATE SET
                duration_seconds = app_usage.duration_seconds + EXCLUDED.duration_seconds,
                session_count = app_usage.session_count + 1,
                last_updated = NOW();
                
            RETURN QUERY SELECT 'success'::text, 'App switch processed'::text;
        EXCEPTION WHEN OTHERS THEN
            RETURN QUERY SELECT 'error'::text, SQLERRM::text;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # 3. Align process_domain_switch_event (10 params expected by server)
    op.execute("DROP FUNCTION IF EXISTS process_domain_switch_event(VARCHAR, VARCHAR, VARCHAR, TEXT, TEXT, VARCHAR, TIMESTAMP, TIMESTAMP, INTEGER, VARCHAR) CASCADE;")
    op.execute("""
        CREATE OR REPLACE FUNCTION process_domain_switch_event(
            p_agent_id VARCHAR, p_username VARCHAR, p_domain VARCHAR,
            p_raw_title TEXT, p_raw_url TEXT, p_browser VARCHAR,
            p_session_start TIMESTAMP, p_session_end TIMESTAMP,
            p_duration_seconds INTEGER, p_idempotency_key VARCHAR
        ) RETURNS TABLE(status text, message text) AS $$
        DECLARE v_date DATE;
        BEGIN
            v_date := p_session_start::DATE;
            INSERT INTO domain_sessions (agent_id, domain, raw_title, raw_url, browser,
                start_time, end_time, duration_seconds, domain_source, needs_review, idempotency_key, created_at)
            VALUES (p_agent_id::UUID, p_domain, p_raw_title, p_raw_url, p_browser,
                p_session_start, p_session_end, p_duration_seconds, 'agent', FALSE, p_idempotency_key, NOW());
            INSERT INTO domain_usage (agent_id, date, domain, duration_seconds, session_count, last_updated)
            VALUES (p_agent_id::UUID, v_date, p_domain, p_duration_seconds, 1, NOW())
            ON CONFLICT (agent_id, date, domain) DO UPDATE SET
                duration_seconds = domain_usage.duration_seconds + EXCLUDED.duration_seconds,
                session_count = domain_usage.session_count + 1,
                last_updated = NOW();
            RETURN QUERY SELECT 'success'::text, 'Domain switch processed'::text;
        EXCEPTION WHEN OTHERS THEN
            RETURN QUERY SELECT 'error'::text, SQLERRM::text;
        END;
        $$ LANGUAGE plpgsql;
    """)


def downgrade() -> None:
    """Downgrade schema."""
    pass
