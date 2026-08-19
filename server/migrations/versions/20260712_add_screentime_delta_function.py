"""add process_screentime_delta function to migration chain

The authoritative state_duration handler (server_telemetry.process_state_duration_event)
calls process_screentime_delta(), but until now the function only existed in the
manual script migrations/add_screentime_delta_procedure.py — a fresh database
built with `alembic upgrade head` was missing it, so every state_duration
telemetry event failed with a 500.

Revision ID: 20260712_screentime_delta_fn
Revises: 20260711_merge_tel_gpu
Create Date: 2026-07-12 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20260712_screentime_delta_fn'
down_revision = '20260711_merge_tel_gpu'
branch_labels = None
depends_on = None


def upgrade():
    # process_screentime_delta - INCREMENTAL ADD model (deltas, not totals).
    # Agent sends the seconds elapsed in a state since its last report and the
    # server adds them to the day's row. Idempotent (CREATE OR REPLACE) so it
    # is safe on databases where the manual script already created it.
    op.execute("""
    CREATE OR REPLACE FUNCTION process_screentime_delta(
        p_agent_id VARCHAR,
        p_timestamp TIMESTAMP,
        p_delta_active INTEGER,
        p_delta_idle INTEGER,
        p_delta_locked INTEGER,
        p_state VARCHAR,
        p_delta_away INTEGER DEFAULT 0
    ) RETURNS TABLE(status text, message text) AS $$
    DECLARE
        v_date DATE;
    BEGIN
        v_date := p_timestamp::DATE;

        -- p_agent_id::uuid: agent_id columns are UUID after c15377a4441b,
        -- and plpgsql does not implicitly cast a VARCHAR parameter to uuid
        -- (the manual-script version of this function failed silently here).
        INSERT INTO screen_time (
            agent_id, date, active_seconds, idle_seconds, locked_seconds, away_seconds, last_updated
        ) VALUES (
            p_agent_id::uuid, v_date, p_delta_active, p_delta_idle, p_delta_locked, p_delta_away, NOW()
        )
        ON CONFLICT (agent_id, date) DO UPDATE SET
            active_seconds = screen_time.active_seconds + EXCLUDED.active_seconds,
            idle_seconds   = screen_time.idle_seconds   + EXCLUDED.idle_seconds,
            locked_seconds = screen_time.locked_seconds + EXCLUDED.locked_seconds,
            away_seconds   = COALESCE(screen_time.away_seconds, 0) + EXCLUDED.away_seconds,
            last_updated   = NOW();

        RETURN QUERY SELECT 'success'::text, 'Screentime delta added'::text;
    EXCEPTION WHEN OTHERS THEN
        RETURN QUERY SELECT 'error'::text, SQLERRM::text;
    END;
    $$ LANGUAGE plpgsql;
    """)


def downgrade():
    op.execute("DROP FUNCTION IF EXISTS process_screentime_delta(VARCHAR, TIMESTAMP, INTEGER, INTEGER, INTEGER, VARCHAR, INTEGER)")
