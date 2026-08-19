"""Add session_start column and update stored procedure for reset detection

When an agent restarts/reinstalls, its cumulative screentime counters reset to zero.
The old GREATEST() logic rejected these lower values, causing stale data.

This migration:
1. Adds session_start column to screen_time table
2. Updates process_screentime_event() to detect session changes
   - Same session: GREATEST() (prevents regression)
   - New session: REPLACE (accepts reset counters)
"""
from alembic import op
import sqlalchemy as sa

revision = '20260218_session_reset'
down_revision = ('007_add_eol_system_tables', 'a7e3b9c12d45')
branch_labels = None
depends_on = None


def upgrade():
    # 1. Add session_start column
    op.execute("""
        ALTER TABLE screen_time
        ADD COLUMN IF NOT EXISTS session_start TIMESTAMP;
    """)

    # 2. Create index for efficient lookups
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_screen_time_session
        ON screen_time(agent_id, date, session_start);
    """)

    # 3. Drop old function signatures to avoid conflicts
    op.execute("DROP FUNCTION IF EXISTS process_screentime_event(VARCHAR, TIMESTAMP, INTEGER, INTEGER, INTEGER, VARCHAR) CASCADE;")
    op.execute("DROP FUNCTION IF EXISTS process_screentime_event(VARCHAR, TIMESTAMP, INTEGER, INTEGER, INTEGER, INTEGER, VARCHAR) CASCADE;")
    op.execute("DROP FUNCTION IF EXISTS process_screentime_event(VARCHAR, DATE, VARCHAR, INTEGER, INTEGER, INTEGER, INTEGER) CASCADE;")

    # 4. Create session-aware stored procedure (8 params)
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

            -- Check if session changed (agent restart/reinstall detection)
            IF p_session_start IS NOT NULL THEN
                SELECT session_start INTO v_existing_session_start
                FROM screen_time
                WHERE agent_id = p_agent_id::UUID AND date = v_date;

                IF v_existing_session_start IS NULL OR
                   v_existing_session_start != p_session_start THEN
                    v_session_changed := TRUE;
                END IF;
            END IF;

            INSERT INTO screen_time (agent_id, date, session_start, active_seconds, idle_seconds, locked_seconds, away_seconds, last_updated)
            VALUES (p_agent_id::UUID, v_date, p_session_start, p_active_total, p_idle_total, p_locked_total, p_away_total, NOW())
            ON CONFLICT (agent_id, date) DO UPDATE SET
                -- Update session_start if changed
                session_start = CASE WHEN v_session_changed
                    THEN EXCLUDED.session_start
                    ELSE screen_time.session_start END,
                -- Session metadata can change, but totals are monotonic cumulative values.
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

    print("[OK] Session-based reset detection installed")
    print("   - Added session_start column to screen_time")
    print("   - Updated process_screentime_event() with session-aware logic")


def downgrade():
    # Revert to original 7-param procedure
    op.execute("DROP FUNCTION IF EXISTS process_screentime_event CASCADE;")
    op.execute("""
        CREATE OR REPLACE FUNCTION process_screentime_event(
            p_agent_id VARCHAR, p_timestamp TIMESTAMP,
            p_active_total INTEGER, p_idle_total INTEGER,
            p_locked_total INTEGER, p_away_total INTEGER,
            p_state VARCHAR
        ) RETURNS TABLE(status text, message text) AS $$
        DECLARE v_date DATE;
        BEGIN
            v_date := p_timestamp::DATE;
            INSERT INTO screen_time (agent_id, date, active_seconds, idle_seconds, locked_seconds, away_seconds, last_updated)
            VALUES (p_agent_id::UUID, v_date, p_active_total, p_idle_total, p_locked_total, p_away_total, NOW())
            ON CONFLICT (agent_id, date) DO UPDATE SET
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

    op.execute("DROP INDEX IF EXISTS idx_screen_time_session;")
    op.execute("ALTER TABLE screen_time DROP COLUMN IF EXISTS session_start;")
    print("[OK] Reverted to GREATEST()-only screentime procedure")
