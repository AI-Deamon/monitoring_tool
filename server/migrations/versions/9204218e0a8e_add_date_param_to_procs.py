"""add date param to procs

Revision ID: 9204218e0a8e
Revises: 7204218e0a8e
Create Date: 2026-09-16 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '9204218e0a8e'
down_revision = '20260819_drop_battery_fields'
branch_labels = None
depends_on = None

def upgrade():
    # 1. Update process_app_switch_event to take p_date
    op.execute("DROP FUNCTION IF EXISTS process_app_switch_event(VARCHAR, TIMESTAMP, VARCHAR, VARCHAR, VARCHAR, VARCHAR, TIMESTAMP, TIMESTAMP, FLOAT) CASCADE;")
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
            p_total_seconds FLOAT,
            p_date DATE
        ) RETURNS TABLE(status text, message text) AS $$
        BEGIN
            INSERT INTO app_sessions (
                agent_id, app, window_title, start_time, end_time, duration_seconds, created_at
            ) VALUES (
                p_agent_id::UUID, p_app, p_window_title, p_session_start, p_session_end, p_total_seconds, NOW()
            );
            
            INSERT INTO app_usage (
                agent_id, date, app, duration_seconds, session_count, last_updated
            ) VALUES (
                p_agent_id::UUID, p_date, p_app, p_total_seconds::INTEGER, 1, NOW()
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

    # 2. Update process_domain_switch_event to take p_date
    op.execute("DROP FUNCTION IF EXISTS process_domain_switch_event(VARCHAR, VARCHAR, VARCHAR, TEXT, TEXT, VARCHAR, TIMESTAMP, TIMESTAMP, INTEGER, VARCHAR) CASCADE;")
    op.execute("""
        CREATE OR REPLACE FUNCTION process_domain_switch_event(
            p_agent_id VARCHAR, p_username VARCHAR, p_domain VARCHAR,
            p_raw_title TEXT, p_raw_url TEXT, p_browser VARCHAR,
            p_session_start TIMESTAMP, p_session_end TIMESTAMP,
            p_duration_seconds INTEGER, p_idempotency_key VARCHAR,
            p_date DATE
        ) RETURNS TABLE(status text, message text) AS $$
        BEGIN
            INSERT INTO domain_sessions (agent_id, domain, raw_title, raw_url, browser,
                start_time, end_time, duration_seconds, domain_source, needs_review, idempotency_key, created_at)
            VALUES (p_agent_id::UUID, p_domain, p_raw_title, p_raw_url, p_browser,
                p_session_start, p_session_end, p_duration_seconds, 'agent', FALSE, p_idempotency_key, NOW());
            INSERT INTO domain_usage (agent_id, date, domain, duration_seconds, session_count, last_updated)
            VALUES (p_agent_id::UUID, p_date, p_domain, p_duration_seconds, 1, NOW())
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
    pass
