"""add sync functions

Revision ID: 20250218_add_sync_functions
Revises: 20250218_add_stored_procedures
Create Date: 2025-02-18 13:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20250218_add_sync_functions'
down_revision = '20250218_add_stored_procedures'
branch_labels = None
depends_on = None


def upgrade():
    # sync_app_usage_from_sessions
    op.execute("""
    CREATE OR REPLACE FUNCTION sync_app_usage_from_sessions(p_date DATE)
    RETURNS void AS $$
    BEGIN
        -- Upsert app_usage based on aggregation of app_sessions
        INSERT INTO app_usage (agent_id, date, app, duration_seconds, session_count, last_updated)
        SELECT 
            agent_id,
            p_date,
            app,
            COALESCE(SUM(duration_seconds), 0)::INTEGER,
            COUNT(*),
            NOW()
        FROM app_sessions
        WHERE start_time::DATE = p_date
        GROUP BY agent_id, app
        ON CONFLICT (agent_id, date, app) DO UPDATE SET
            duration_seconds = EXCLUDED.duration_seconds,
            session_count = EXCLUDED.session_count,
            last_updated = NOW();
    END;
    $$ LANGUAGE plpgsql;
    """)

    # sync_domain_usage_from_sessions
    op.execute("""
    CREATE OR REPLACE FUNCTION sync_domain_usage_from_sessions(p_date DATE)
    RETURNS void AS $$
    BEGIN
        -- Upsert domain_usage based on aggregation of domain_sessions
        INSERT INTO domain_usage (agent_id, date, domain, duration_seconds, session_count, last_updated)
        SELECT 
            agent_id,
            p_date,
            domain,
            COALESCE(SUM(duration_seconds), 0)::INTEGER,
            COUNT(*),
            NOW()
        FROM domain_sessions
        WHERE start_time::DATE = p_date
        GROUP BY agent_id, domain
        ON CONFLICT (agent_id, date, domain) DO UPDATE SET
            duration_seconds = EXCLUDED.duration_seconds,
            session_count = EXCLUDED.session_count,
            last_updated = NOW();
    END;
    $$ LANGUAGE plpgsql;
    """)

    # sync_screen_time_from_sessions
    # Only updates active_seconds from app_sessions (Source of Truth for active time)
    # Leaves idle/locked seconds alone (as they come from telemetry/StateChanges)
    op.execute("""
    CREATE OR REPLACE FUNCTION sync_screen_time_from_sessions(p_date DATE)
    RETURNS TABLE(agent_id VARCHAR, active_seconds INTEGER) AS $$
    DECLARE
        r RECORD;
    BEGIN
        FOR r IN 
            SELECT 
                s.agent_id,
                COALESCE(SUM(s.duration_seconds), 0)::INTEGER as total_active
            FROM app_sessions s
            WHERE s.start_time::DATE = p_date
            GROUP BY s.agent_id
        LOOP
            -- Upsert screen_time
            INSERT INTO screen_time (agent_id, date, active_seconds, idle_seconds, locked_seconds, last_updated)
            VALUES (r.agent_id, p_date, r.total_active, 0, 0, NOW())
            ON CONFLICT (agent_id, date) DO UPDATE SET
                active_seconds = EXCLUDED.active_seconds,
                last_updated = NOW();
                
            agent_id := r.agent_id;
            active_seconds := r.total_active;
            RETURN NEXT;
        END LOOP;
        RETURN;
    END;
    $$ LANGUAGE plpgsql;
    """)


def downgrade():
    op.execute("DROP FUNCTION IF EXISTS sync_app_usage_from_sessions(DATE);")
    op.execute("DROP FUNCTION IF EXISTS sync_domain_usage_from_sessions(DATE);")
    op.execute("DROP FUNCTION IF EXISTS sync_screen_time_from_sessions(DATE);")
