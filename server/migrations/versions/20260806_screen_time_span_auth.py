"""screen_time spans are authoritative for fully-elapsed days

Redefines sync_screen_time_from_spans(p_date DATE) as a reconcile-and-set
procedure: for a fully-elapsed UTC day it OVERWRITES the screen_time row
from the sum of ALL that day's spans (not just unprocessed ones), caps each
bucket at 86400, and zeroes existing rows for span-capable agents that have
no spans that day. Pre-span-era agents (no span ever) are left untouched.

Revision ID: 20260806_screen_time_span_auth
Revises: 20260730_cap_usage_sync_at_24h
Create Date: 2026-08-06
"""
from alembic import op

revision = '20260806_screen_time_span_auth'
down_revision = '20260730_cap_usage_sync_at_24h'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE OR REPLACE FUNCTION sync_screen_time_from_spans(p_date DATE DEFAULT CURRENT_DATE)
        RETURNS TABLE(ret_agent_id UUID, synced BOOLEAN) AS $$
        BEGIN
            -- Reconcile-and-set: overwrite the row from the FULL span sum for
            -- p_date. No processed gate — late spans must count even after an
            -- earlier run already marked that day's spans processed (FR-006).
            -- No additive merge — a downward correction (e.g. a fabricated
            -- cumulative total) is replaced, not ratcheted up.
            INSERT INTO screen_time (agent_id, date, active_seconds, idle_seconds, locked_seconds, away_seconds, last_updated, updated_at)
            SELECT
                s.agent_id,
                p_date,
                LEAST(COALESCE(SUM(CASE WHEN s.state = 'active' THEN s.duration_seconds ELSE 0 END), 0), 86400)::INTEGER,
                LEAST(COALESCE(SUM(CASE WHEN s.state = 'idle'   THEN s.duration_seconds ELSE 0 END), 0), 86400)::INTEGER,
                LEAST(COALESCE(SUM(CASE WHEN s.state = 'locked' THEN s.duration_seconds ELSE 0 END), 0), 86400)::INTEGER,
                LEAST(COALESCE(SUM(CASE WHEN s.state = 'away'   THEN s.duration_seconds ELSE 0 END), 0), 86400)::INTEGER,
                NOW(),
                NOW()
            FROM screen_time_spans s
            JOIN agents a ON a.agent_id = s.agent_id
            WHERE s.start_time::DATE = p_date
            GROUP BY s.agent_id
            ON CONFLICT (agent_id, date) DO UPDATE SET
                active_seconds = EXCLUDED.active_seconds,
                idle_seconds = EXCLUDED.idle_seconds,
                locked_seconds = EXCLUDED.locked_seconds,
                away_seconds = EXCLUDED.away_seconds,
                last_updated = NOW(),
                updated_at = NOW();

            -- Capability-gated zeroing: an existing row for p_date whose
            -- agent has no spans that day is zeroed ONLY if the agent had
            -- ALREADY produced at least one span BY p_date (not merely "ever,
            -- as of now"). Date-scoping matters: an agent that sends its
            -- first-ever span on day X must not have its genuinely
            -- pre-upgrade days (X-1..X-6) zeroed just because a later sweep
            -- run sees the agent as globally capable. Pre-span-era agents
            -- (zero spans ever) are never touched (FR-006 gate / US3-7).
            -- Never creates rows for agents with no data — this only updates
            -- rows that already exist.
            UPDATE screen_time st
            SET active_seconds = 0, idle_seconds = 0, locked_seconds = 0,
                away_seconds = 0, last_updated = NOW(), updated_at = NOW()
            WHERE st.date = p_date
              AND NOT EXISTS (
                  SELECT 1 FROM screen_time_spans sp
                  WHERE sp.agent_id = st.agent_id AND sp.start_time::DATE = p_date
              )
              AND EXISTS (
                  SELECT 1 FROM screen_time_spans hist
                  WHERE hist.agent_id = st.agent_id AND hist.start_time::DATE <= p_date
              );

            -- Mark the day's spans processed so the 7-day span cleanup can
            -- purge them. Reconcile still reads ALL spans for p_date, so a
            -- late span counted on a later run even after this marking.
            UPDATE screen_time_spans
            SET processed = TRUE
            WHERE start_time::DATE = p_date;

            -- Return affected agents (span-aggregated + capability-zeroed).
            RETURN QUERY
            SELECT DISTINCT agent_id, TRUE AS synced
            FROM (
                SELECT s.agent_id FROM screen_time_spans s
                JOIN agents a ON a.agent_id = s.agent_id
                WHERE s.start_time::DATE = p_date
                UNION
                SELECT st.agent_id FROM screen_time st
                WHERE st.date = p_date
                  AND NOT EXISTS (
                      SELECT 1 FROM screen_time_spans sp
                      WHERE sp.agent_id = st.agent_id AND sp.start_time::DATE = p_date
                  )
                  AND EXISTS (
                      SELECT 1 FROM screen_time_spans hist
                      WHERE hist.agent_id = st.agent_id AND hist.start_time::DATE <= p_date
                  )
            ) AS touched;
        END;
        $$ LANGUAGE plpgsql;
    """)


def downgrade():
    op.execute("""
        CREATE OR REPLACE FUNCTION sync_screen_time_from_spans(p_date DATE DEFAULT CURRENT_DATE)
        RETURNS TABLE(ret_agent_id UUID, synced BOOLEAN) AS $$
        BEGIN
            -- Insert/update screen_time from unprocessed spans
            INSERT INTO screen_time (agent_id, date, active_seconds, idle_seconds, locked_seconds)
            SELECT
                s.agent_id,
                s.start_time::DATE as span_date,
                SUM(CASE WHEN s.state = 'active' THEN s.duration_seconds ELSE 0 END) as active_sec,
                SUM(CASE WHEN s.state = 'idle' THEN s.duration_seconds ELSE 0 END) as idle_sec,
                SUM(CASE WHEN s.state = 'locked' THEN s.duration_seconds ELSE 0 END) as locked_sec
            FROM screen_time_spans s
            WHERE s.start_time::DATE = p_date
              AND s.processed = FALSE
            GROUP BY s.agent_id, s.start_time::DATE
            ON CONFLICT (agent_id, date)
            DO UPDATE SET
                active_seconds = screen_time.active_seconds + EXCLUDED.active_seconds,
                idle_seconds = screen_time.idle_seconds + EXCLUDED.idle_seconds,
                locked_seconds = screen_time.locked_seconds + EXCLUDED.locked_seconds,
                updated_at = NOW();

            -- Mark spans as processed
            UPDATE screen_time_spans
            SET processed = TRUE
            WHERE start_time::DATE = p_date AND processed = FALSE;

            -- Return affected agents
            RETURN QUERY
            SELECT DISTINCT s.agent_id, TRUE as synced
            FROM screen_time_spans s
            WHERE s.start_time::DATE = p_date;
        END;
        $$ LANGUAGE plpgsql;
    """)
