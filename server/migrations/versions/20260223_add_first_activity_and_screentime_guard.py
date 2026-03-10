"""Add first_activity_at and enforce monotonic screentime procedure.

Revision ID: 20260223_first_activity_guard
Revises: 20260218_session_reset
Create Date: 2026-02-23
"""
from alembic import op


revision = '20260223_first_activity_guard'
down_revision = '20260218_session_reset'
branch_labels = None
depends_on = None


def upgrade():
    # 1) Canonical first activity timestamp on agents.
    op.execute("""
        ALTER TABLE agents
        ADD COLUMN IF NOT EXISTS first_activity_at TIMESTAMP NULL;
    """)

    # 2) Backfill from earliest known telemetry activity.
    op.execute("""
        WITH firsts AS (
            SELECT
                a.agent_id,
                LEAST(
                    COALESCE((SELECT MIN(ap.start_time) FROM app_sessions ap WHERE ap.agent_id = a.agent_id), '9999-12-31'::timestamp),
                    COALESCE((SELECT MIN(ds.start_time) FROM domain_sessions ds WHERE ds.agent_id = a.agent_id), '9999-12-31'::timestamp),
                    COALESCE((SELECT MIN(st.date::timestamp) FROM screen_time st WHERE st.agent_id = a.agent_id), '9999-12-31'::timestamp),
                    COALESCE((SELECT MIN(sc.timestamp) FROM state_changes sc WHERE sc.agent_id = a.agent_id), '9999-12-31'::timestamp)
                ) AS first_activity
            FROM agents a
        )
        UPDATE agents a
        SET first_activity_at = CASE
            WHEN f.first_activity = '9999-12-31'::timestamp THEN NULL
            ELSE f.first_activity
        END
        FROM firsts f
        WHERE a.agent_id = f.agent_id
          AND a.first_activity_at IS NULL;
    """)

    # 3) Recreate screentime procedure as monotonic-only merge.
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


def downgrade():
    op.execute("""
        ALTER TABLE agents
        DROP COLUMN IF EXISTS first_activity_at;
    """)
