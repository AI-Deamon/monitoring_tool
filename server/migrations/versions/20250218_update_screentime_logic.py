"""update screentime logic

Revision ID: 20250218_update_screentime_logic
Revises: 20250218_add_sync_functions
Create Date: 2025-02-18 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20250218_update_screentime_logic'
down_revision = '20250218_add_sync_functions'
branch_labels = None
depends_on = None


def upgrade():
    # process_screentime_event - UPDATED to use REPLACE logic (Daily Totals)
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
            -- Replace with new total from agent (Source of Truth)
            active_seconds = GREATEST(screen_time.active_seconds, EXCLUDED.active_seconds),
            idle_seconds = GREATEST(screen_time.idle_seconds, EXCLUDED.idle_seconds),
            locked_seconds = GREATEST(screen_time.locked_seconds, EXCLUDED.locked_seconds),
            last_updated = NOW();
            
        RETURN QUERY SELECT 'success'::text, 'Screentime processed (total)'::text;
    EXCEPTION WHEN OTHERS THEN
        RETURN QUERY SELECT 'error'::text, SQLERRM::text;
    END;
    $$ LANGUAGE plpgsql;
    """)

def downgrade():
    # Revert to incremental logic (simplified)
    op.execute("""
    CREATE OR REPLACE FUNCTION process_screentime_event(
        p_agent_id VARCHAR,
        p_timestamp TIMESTAMP,
        p_active_inc INTEGER,
        p_idle_inc INTEGER,
        p_locked_inc INTEGER,
        p_state VARCHAR
    ) RETURNS TABLE(status text, message text) AS $$
    DECLARE
        v_date DATE;
    BEGIN
        v_date := p_timestamp::DATE;
        
        INSERT INTO screen_time (
            agent_id, date, active_seconds, idle_seconds, locked_seconds, last_updated
        ) VALUES (
            p_agent_id, v_date, p_active_inc, p_idle_inc, p_locked_inc, NOW()
        )
        ON CONFLICT (agent_id, date) DO UPDATE SET
            active_seconds = screen_time.active_seconds + EXCLUDED.active_seconds,
            idle_seconds = screen_time.idle_seconds + EXCLUDED.idle_seconds,
            locked_seconds = screen_time.locked_seconds + EXCLUDED.locked_seconds,
            last_updated = NOW();
            
        RETURN QUERY SELECT 'success'::text, 'Screentime processed'::text;
    END;
    $$ LANGUAGE plpgsql;
    """)
