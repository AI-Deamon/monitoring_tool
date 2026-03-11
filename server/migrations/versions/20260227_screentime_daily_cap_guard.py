"""Add LEAST(86400) daily cap guard to process_screentime_event

Prevents any individual screen time counter (active, idle, locked, away)
from exceeding 24 hours (86400 seconds) per day. Defense-in-depth against
clock jumps or stale cumulative values after sleep/wake cycles.

Revision ID: 20260227_daily_cap
Revises: 20260223
"""
from alembic import op

revision = '20260227_daily_cap'
down_revision = '20260223_first_activity_guard'
branch_labels = None
depends_on = None


def upgrade():
    # Recreate process_screentime_event with LEAST(86400) caps
    op.execute("DROP FUNCTION IF EXISTS process_screentime_event(VARCHAR, TIMESTAMP, INTEGER, INTEGER, INTEGER, INTEGER, VARCHAR, TIMESTAMP) CASCADE;")
    op.execute("""
        CREATE OR REPLACE FUNCTION process_screentime_event(
            p_agent_id VARCHAR, p_timestamp TIMESTAMP,
            p_active_total INTEGER, p_idle_total INTEGER,
            p_locked_total INTEGER, p_away_total INTEGER,
            p_state VARCHAR,
            p_session_start TIMESTAMP DEFAULT NULL
        ) RETURNS TABLE(status text, message text) AS $$
        DECLARE
            v_date DATE;
            v_existing_session_start TIMESTAMP;
            v_session_changed BOOLEAN := FALSE;
        BEGIN
            v_date := p_timestamp::DATE;

            IF p_session_start IS NOT NULL THEN
                SELECT session_start INTO v_existing_session_start
                FROM screen_time
                WHERE agent_id = p_agent_id::UUID AND date = v_date;

                IF v_existing_session_start IS NULL OR v_existing_session_start != p_session_start THEN
                    v_session_changed := TRUE;
                END IF;
            END IF;

            INSERT INTO screen_time (agent_id, date, session_start, active_seconds, idle_seconds, locked_seconds, away_seconds, last_updated)
            VALUES (p_agent_id::UUID, v_date, p_session_start, p_active_total, p_idle_total, p_locked_total, p_away_total, NOW())
            ON CONFLICT (agent_id, date) DO UPDATE SET
                session_start = CASE WHEN v_session_changed THEN EXCLUDED.session_start ELSE screen_time.session_start END,
                -- LEAST(86400) caps each counter at 24h as defense-in-depth against clock jumps.
                active_seconds = LEAST(GREATEST(screen_time.active_seconds, EXCLUDED.active_seconds), 86400),
                idle_seconds = LEAST(GREATEST(screen_time.idle_seconds, EXCLUDED.idle_seconds), 86400),
                locked_seconds = LEAST(GREATEST(screen_time.locked_seconds, EXCLUDED.locked_seconds), 86400),
                away_seconds = LEAST(GREATEST(screen_time.away_seconds, EXCLUDED.away_seconds), 86400),
                last_updated = NOW();

            RETURN QUERY SELECT 'success'::text, 'Screentime processed'::text;
        EXCEPTION WHEN OTHERS THEN
            RETURN QUERY SELECT 'error'::text, SQLERRM::text;
        END;
        $$ LANGUAGE plpgsql;
    """)
    print("  Updated process_screentime_event with LEAST(86400) daily cap guard")


def downgrade():
    # Revert to version without LEAST() caps
    op.execute("DROP FUNCTION IF EXISTS process_screentime_event CASCADE;")
    op.execute("""
        CREATE OR REPLACE FUNCTION process_screentime_event(
            p_agent_id VARCHAR, p_timestamp TIMESTAMP,
            p_active_total INTEGER, p_idle_total INTEGER,
            p_locked_total INTEGER, p_away_total INTEGER,
            p_state VARCHAR,
            p_session_start TIMESTAMP DEFAULT NULL
        ) RETURNS TABLE(status text, message text) AS $$
        DECLARE
            v_date DATE;
            v_existing_session_start TIMESTAMP;
            v_session_changed BOOLEAN := FALSE;
        BEGIN
            v_date := p_timestamp::DATE;

            IF p_session_start IS NOT NULL THEN
                SELECT session_start INTO v_existing_session_start
                FROM screen_time
                WHERE agent_id = p_agent_id::UUID AND date = v_date;

                IF v_existing_session_start IS NULL OR v_existing_session_start != p_session_start THEN
                    v_session_changed := TRUE;
                END IF;
            END IF;

            INSERT INTO screen_time (agent_id, date, session_start, active_seconds, idle_seconds, locked_seconds, away_seconds, last_updated)
            VALUES (p_agent_id::UUID, v_date, p_session_start, p_active_total, p_idle_total, p_locked_total, p_away_total, NOW())
            ON CONFLICT (agent_id, date) DO UPDATE SET
                session_start = CASE WHEN v_session_changed THEN EXCLUDED.session_start ELSE screen_time.session_start END,
                active_seconds = GREATEST(screen_time.active_seconds, EXCLUDED.active_seconds),
                idle_seconds = GREATEST(screen_time.idle_seconds, EXCLUDED.idle_seconds),
                locked_seconds = GREATEST(screen_time.locked_seconds, EXCLUDED.locked_seconds),
                away_seconds = GREATEST(screen_time.away_seconds, EXCLUDED.away_seconds),
                last_updated = NOW();

            RETURN QUERY SELECT 'success'::text, 'Screentime processed'::text;
        EXCEPTION WHEN OTHERS THEN
            RETURN QUERY SELECT 'error'::text, SQLERRM::text;
        END;
        $$ LANGUAGE plpgsql;
    """)
