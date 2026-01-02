"""add stored procedures

Revision ID: 20250218_add_stored_procedures
Revises: 87b72471d98c
Create Date: 2025-02-18 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20250218_add_stored_procedures'
down_revision = '87b72471d98c'
branch_labels = None
depends_on = None


def upgrade():
    # process_screentime_event - Uses REPLACE with GREATEST logic (Daily Totals)
    # Agent sends cumulative daily totals, server stores them using GREATEST
    # to prevent regression if agent restarts mid-day
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
            p_agent_id, v_date, p_active_total, p_idle_total, p_locked_total, NOW()
        )
        ON CONFLICT (agent_id, date) DO UPDATE SET
            -- Replace with new total from agent using GREATEST (Source of Truth)
            -- GREATEST prevents regression if agent restarts and sends smaller values
            active_seconds = GREATEST(screen_time.active_seconds, EXCLUDED.active_seconds),
            idle_seconds = GREATEST(screen_time.idle_seconds, EXCLUDED.idle_seconds),
            locked_seconds = GREATEST(screen_time.locked_seconds, EXCLUDED.locked_seconds),
            last_updated = NOW();
            
        RETURN QUERY SELECT 'success'::text, 'Screentime processed (daily total)'::text;
    EXCEPTION WHEN OTHERS THEN
        RETURN QUERY SELECT 'error'::text, SQLERRM::text;
    END;
    $$ LANGUAGE plpgsql;
    """)

    # process_app_switch_event
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
        
        -- 1. Insert into app_sessions (History)
        INSERT INTO app_sessions (
            agent_id, app, window_title, start_time, end_time, duration_seconds, created_at
        ) VALUES (
            p_agent_id, p_app, p_window_title, p_session_start, p_session_end, p_total_seconds, NOW()
        );
        
        -- 2. Upsert into app_usage (Daily Aggregation)
        INSERT INTO app_usage (
            agent_id, date, app, duration_seconds, session_count, last_updated
        ) VALUES (
            p_agent_id, v_date, p_app, p_total_seconds::INTEGER, 1, NOW()
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

    # process_domain_switch_event
    op.execute("""
    CREATE OR REPLACE FUNCTION process_domain_switch_event(
        p_agent_id VARCHAR,
        p_timestamp TIMESTAMP,
        p_domain VARCHAR,
        p_browser VARCHAR,
        p_url TEXT,
        p_session_start TIMESTAMP,
        p_session_end TIMESTAMP,
        p_total_seconds FLOAT
    ) RETURNS TABLE(status text, message text) AS $$
    DECLARE
        v_date DATE;
    BEGIN
        v_date := p_session_start::DATE;
        
        -- 1. Insert into domain_sessions (History)
        INSERT INTO domain_sessions (
            agent_id, domain, browser, url, start_time, end_time, duration_seconds, created_at
        ) VALUES (
            p_agent_id, p_domain, p_browser, p_url, p_session_start, p_session_end, p_total_seconds, NOW()
        );
        
        -- 2. Upsert into domain_usage (Daily Aggregation)
        INSERT INTO domain_usage (
            agent_id, date, domain, browser, duration_seconds, session_count, last_updated
        ) VALUES (
            p_agent_id, v_date, p_domain, p_browser, p_total_seconds::INTEGER, 1, NOW()
        )
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


def downgrade():
    op.execute("DROP FUNCTION IF EXISTS process_screentime_event(VARCHAR, TIMESTAMP, INTEGER, INTEGER, INTEGER, VARCHAR);")
    op.execute("DROP FUNCTION IF EXISTS process_app_switch_event(VARCHAR, TIMESTAMP, VARCHAR, VARCHAR, VARCHAR, VARCHAR, TIMESTAMP, TIMESTAMP, FLOAT);")
    op.execute("DROP FUNCTION IF EXISTS process_domain_switch_event(VARCHAR, TIMESTAMP, VARCHAR, VARCHAR, TEXT, TIMESTAMP, TIMESTAMP, FLOAT);")
