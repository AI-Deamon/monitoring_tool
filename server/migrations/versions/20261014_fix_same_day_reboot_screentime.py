"""Fix same-day reboot screen time loss: use GREATEST merge and safe session start in process_screentime_event

Revision ID: 20261014_fix_reboot_screentime
Revises: 20260916_fix_span_reconcile
Create Date: 2026-10-14
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = '20261014_fix_reboot_screentime'
down_revision = '20260916_fix_span_reconcile'
branch_labels = None
depends_on = None


def upgrade():
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
            v_existing_total INTEGER := 0;
            v_incoming_total INTEGER := 0;
            v_should_replace BOOLEAN := FALSE;
        BEGIN
            v_date := p_timestamp::DATE;
            IF v_date < (NOW() AT TIME ZONE 'Asia/Kolkata')::DATE THEN
                RAISE NOTICE 'Historical data detected for agent %, on %', p_agent_id, v_date;
            END IF;

            SELECT
                session_start,
                COALESCE(active_seconds, 0)::INTEGER +
                COALESCE(idle_seconds, 0)::INTEGER +
                COALESCE(locked_seconds, 0)::INTEGER +
                COALESCE(away_seconds, 0)::INTEGER
            INTO v_existing_session_start, v_existing_total
            FROM screen_time
            WHERE agent_id = p_agent_id::UUID AND date = v_date;

            IF p_session_start IS NOT NULL THEN
                IF v_existing_session_start IS NULL OR v_existing_session_start != p_session_start THEN
                    v_session_changed := TRUE;
                END IF;
            END IF;

            v_incoming_total := COALESCE(p_active_total, 0) +
                COALESCE(p_idle_total, 0) +
                COALESCE(p_locked_total, 0) +
                COALESCE(p_away_total, 0);

            -- v_should_replace is strictly true when the incoming total >= existing total.
            -- A session change (e.g. reboot mid-day) must NEVER drop cumulative seconds!
            v_should_replace := (v_incoming_total >= v_existing_total);

            INSERT INTO screen_time (agent_id, date, session_start, active_seconds, idle_seconds, locked_seconds, away_seconds, last_updated)
            VALUES (p_agent_id::UUID, v_date, p_session_start, p_active_total, p_idle_total, p_locked_total, p_away_total, (NOW() AT TIME ZONE 'Asia/Kolkata'))
            ON CONFLICT (agent_id, date) DO UPDATE SET
                session_start = COALESCE(screen_time.session_start, EXCLUDED.session_start),
                active_seconds = CASE
                    WHEN v_should_replace THEN LEAST(EXCLUDED.active_seconds, 86400)
                    ELSE LEAST(GREATEST(screen_time.active_seconds, EXCLUDED.active_seconds), 86400)
                END,
                idle_seconds = CASE
                    WHEN v_should_replace THEN LEAST(EXCLUDED.idle_seconds, 86400)
                    ELSE LEAST(GREATEST(screen_time.idle_seconds, EXCLUDED.idle_seconds), 86400)
                END,
                locked_seconds = CASE
                    WHEN v_should_replace THEN LEAST(EXCLUDED.locked_seconds, 86400)
                    ELSE LEAST(GREATEST(screen_time.locked_seconds, EXCLUDED.locked_seconds), 86400)
                END,
                away_seconds = CASE
                    WHEN v_should_replace THEN LEAST(EXCLUDED.away_seconds, 86400)
                    ELSE LEAST(GREATEST(screen_time.away_seconds, EXCLUDED.away_seconds), 86400)
                END,
                last_updated = (NOW() AT TIME ZONE 'Asia/Kolkata');

            RETURN QUERY SELECT 'success'::text, 'Screentime processed'::text;
        EXCEPTION WHEN OTHERS THEN
            RETURN QUERY SELECT 'error'::text, SQLERRM::text;
        END;
        $$ LANGUAGE plpgsql;
    """)


def downgrade():
    # Restore previous procedure definition from 20260403_fix_screentime_reclassification
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
            v_existing_total INTEGER := 0;
            v_incoming_total INTEGER := 0;
            v_should_replace BOOLEAN := FALSE;
        BEGIN
            v_date := p_timestamp::DATE;
            IF v_date < (NOW() AT TIME ZONE 'Asia/Kolkata')::DATE THEN
                RAISE NOTICE 'Historical data detected for agent %, on %', p_agent_id, v_date;
            END IF;

            SELECT
                session_start,
                COALESCE(active_seconds, 0)::INTEGER +
                COALESCE(idle_seconds, 0)::INTEGER +
                COALESCE(locked_seconds, 0)::INTEGER +
                COALESCE(away_seconds, 0)::INTEGER
            INTO v_existing_session_start, v_existing_total
            FROM screen_time
            WHERE agent_id = p_agent_id::UUID AND date = v_date;

            IF p_session_start IS NOT NULL THEN
                IF v_existing_session_start IS NULL OR v_existing_session_start != p_session_start THEN
                    v_session_changed := TRUE;
                END IF;
            END IF;

            v_incoming_total := COALESCE(p_active_total, 0) +
                COALESCE(p_idle_total, 0) +
                COALESCE(p_locked_total, 0) +
                COALESCE(p_away_total, 0);

            v_should_replace := v_session_changed OR v_incoming_total >= v_existing_total;

            INSERT INTO screen_time (agent_id, date, session_start, active_seconds, idle_seconds, locked_seconds, away_seconds, last_updated)
            VALUES (p_agent_id::UUID, v_date, p_session_start, p_active_total, p_idle_total, p_locked_total, p_away_total, (NOW() AT TIME ZONE 'Asia/Kolkata'))
            ON CONFLICT (agent_id, date) DO UPDATE SET
                session_start = CASE WHEN v_session_changed THEN EXCLUDED.session_start ELSE screen_time.session_start END,
                active_seconds = CASE
                    WHEN v_should_replace THEN LEAST(EXCLUDED.active_seconds, 86400)
                    ELSE screen_time.active_seconds
                END,
                idle_seconds = CASE
                    WHEN v_should_replace THEN LEAST(EXCLUDED.idle_seconds, 86400)
                    ELSE screen_time.idle_seconds
                END,
                locked_seconds = CASE
                    WHEN v_should_replace THEN LEAST(EXCLUDED.locked_seconds, 86400)
                    ELSE screen_time.locked_seconds
                END,
                away_seconds = CASE
                    WHEN v_should_replace THEN LEAST(EXCLUDED.away_seconds, 86400)
                    ELSE screen_time.away_seconds
                END,
                last_updated = (NOW() AT TIME ZONE 'Asia/Kolkata');

            RETURN QUERY SELECT 'success'::text, 'Screentime processed'::text;
        EXCEPTION WHEN OTHERS THEN
            RETURN QUERY SELECT 'error'::text, SQLERRM::text;
        END;
        $$ LANGUAGE plpgsql;
    """)
