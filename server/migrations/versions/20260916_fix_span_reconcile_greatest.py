"""Fix sync_screen_time_from_spans: GREATEST merge instead of hard overwrite

Root cause of end-of-day screen time data loss (v4.2.6):
  sync_screen_time_from_spans() ran at 02:15 UTC and unconditionally
  overwrote screen_time.active_seconds with the span sum for that day.
  When an agent had a network gap or crash late in the day (e.g. 17:05
  IST) and its spans for the remainder of the session (17:05-19:33 IST)
  had not yet reached the server, the nightly reconcile replaced the
  correct ratcheted total (8.37h) with the incomplete span sum (6.01h),
  silently losing 2h 27m of work.

  Observed fleet-wide: 60h of confirmed end-of-day loss, 116h of
  mid-day gaps across 13-17 of ~40 agents daily, all on v4.2.6.

Fix (Option A):
  Replace the ON CONFLICT hard overwrite with a GREATEST merge so that
  the nightly reconcile can only raise the stored total, never lower it.
  This is consistent with process_screentime_event which already uses
  GREATEST for the live-day write path.

  The aggressive zeroing clause (zeros agents with no spans for a date)
  is also removed: it was responsible for the mid-day gap losses where
  agents whose entire day lacked spans (offline until midday) had their
  pre-existing ratcheted row zeroed out.

One-time backfill:
  Restores the most defensible value for rows where the nightly sweep
  already ran and replaced a higher ratcheted value with a lower span
  sum. For each affected agent-date we set active_seconds back to the
  maximum value seen in raw_events so the data is as accurate as
  possible. Rows where the current value >= any raw_event total are left
  unchanged.

Revision ID: 20260916_fix_span_reconcile_greatest
Revises: 9204218e0a8e
Create Date: 2026-09-16
"""
from alembic import op

revision = '20260916_fix_span_reconcile'
down_revision = '9204218e0a8e'
branch_labels = None
depends_on = None


def upgrade():
    # ------------------------------------------------------------------ #
    # 1. Redefine sync_screen_time_from_spans with GREATEST merge          #
    # ------------------------------------------------------------------ #
    op.execute("""
        CREATE OR REPLACE FUNCTION sync_screen_time_from_spans(p_date DATE DEFAULT CURRENT_DATE)
        RETURNS TABLE(ret_agent_id UUID, synced BOOLEAN) AS $$
        BEGIN
            -- Reconcile-and-set using GREATEST merge so that a partial span
            -- set (e.g. agent was offline for the last 2h of the day and
            -- spans for those 2h have not yet arrived) can never lower the
            -- screen_time row below the value already ratcheted there by
            -- process_screentime_event during the live day.
            --
            -- No processed gate: late spans must count even after an
            -- earlier run already marked that day's spans processed (FR-006).
            --
            -- GREATEST replaces the hard EXCLUDED.* overwrite that was
            -- introduced in 20260806_screen_time_span_auth and caused the
            -- v4.2.6 end-of-day data loss.
            INSERT INTO screen_time (
                agent_id, date,
                active_seconds, idle_seconds, locked_seconds, away_seconds,
                last_updated, updated_at
            )
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
                -- GREATEST: span reconcile can only raise, never lower.
                -- Protects against partial-span-coverage overwrite (v4.2.6 bug).
                active_seconds = GREATEST(screen_time.active_seconds, EXCLUDED.active_seconds),
                idle_seconds   = GREATEST(screen_time.idle_seconds,   EXCLUDED.idle_seconds),
                locked_seconds = GREATEST(screen_time.locked_seconds, EXCLUDED.locked_seconds),
                away_seconds   = GREATEST(screen_time.away_seconds,   EXCLUDED.away_seconds),
                last_updated   = NOW(),
                updated_at     = NOW();

            -- NOTE: The aggressive zeroing clause that was present in
            -- 20260806_screen_time_span_auth has been intentionally removed.
            --
            -- That clause zeroed rows for span-capable agents that had no
            -- spans for p_date. This caused the 116h of mid-day gap losses
            -- observed in the fleet: agents that were offline for an entire
            -- morning would have their existing ratcheted row zeroed as soon
            -- as the sweep ran, even though the row was correct.
            --
            -- Spans remain the authoritative source for RAISING the total;
            -- zeroing based on absence-of-spans is too aggressive and is
            -- removed here.

            -- Mark the day's spans processed so the 7-day span cleanup can
            -- purge them. Reconcile still reads ALL spans for p_date, so a
            -- late span is counted on a later run even after this marking.
            UPDATE screen_time_spans
            SET processed = TRUE
            WHERE start_time::DATE = p_date;

            -- Return affected agents (span-aggregated).
            RETURN QUERY
            SELECT DISTINCT s.agent_id, TRUE AS synced
            FROM screen_time_spans s
            JOIN agents a ON a.agent_id = s.agent_id
            WHERE s.start_time::DATE = p_date;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # ------------------------------------------------------------------ #
    # 2. One-time backfill: restore rows already damaged by the overwrite  #
    # ------------------------------------------------------------------ #
    #
    # For every (agent_id, date) row in screen_time where the stored value
    # is LOWER than the maximum cumulative active_seconds seen in raw_events
    # for that agent-date, restore the higher value.
    #
    # raw_events stores the JSON payload of every /telemetry/screentime POST.
    # The cumulative active_seconds in those payloads is the ratcheted total
    # that process_screentime_event would have stored -- the value the nightly
    # overwrite replaced.
    #
    # Only rows that are candidates for having been damaged (i.e. the agent
    # has at least one span for that date, meaning the sweep ran on it) are
    # touched. Pre-span-era agents are left untouched.
    #
    # This is a best-effort recovery: raw_events are retained for 7 days by
    # the cleanup job, so agents whose damage predates 7 days ago cannot be
    # automatically recovered here.
    op.execute("""
        DO $$
        DECLARE
            v_updated INTEGER := 0;
        BEGIN
            -- Guard: only run if required tables exist
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.tables WHERE table_name = 'raw_events'
            ) OR NOT EXISTS (
                SELECT 1 FROM information_schema.tables WHERE table_name = 'screen_time_spans'
            ) THEN
                RAISE NOTICE 'Backfill skipped: required tables not found';
                RETURN;
            END IF;

            -- Extract the best (highest) cumulative totals from raw_events
            -- screentime payloads, then raise screen_time rows that are
            -- currently lower than that best value.
            WITH raw_best AS (
                SELECT
                    agent_id::UUID AS agent_id,
                    -- Extract the local calendar date the agent intended this
                    -- record for (mirrors parse_agent_timestamp / telemetry_screentime
                    -- in server_telemetry.py: use the IST offset the agent sends).
                    (
                        (payload::jsonb ->> 'timestamp')::TIMESTAMPTZ
                        AT TIME ZONE 'Asia/Kolkata'
                    )::DATE AS record_date,
                    MAX((payload::jsonb ->> 'active_seconds')::INTEGER) AS best_active,
                    MAX((payload::jsonb ->> 'idle_seconds')::INTEGER)   AS best_idle,
                    MAX((payload::jsonb ->> 'locked_seconds')::INTEGER) AS best_locked,
                    MAX((payload::jsonb ->> 'away_seconds')::INTEGER)   AS best_away
                FROM raw_events
                WHERE event_type = 'screentime'
                  AND payload IS NOT NULL
                  AND processed = TRUE
                  -- Only look back 14 days to bound the scan
                  AND received_at >= NOW() - INTERVAL '14 days'
                GROUP BY agent_id, record_date
            ),
            damaged AS (
                SELECT
                    st.agent_id,
                    st.date,
                    GREATEST(st.active_seconds, COALESCE(rb.best_active, 0)) AS restored_active,
                    GREATEST(st.idle_seconds,   COALESCE(rb.best_idle,   0)) AS restored_idle,
                    GREATEST(st.locked_seconds, COALESCE(rb.best_locked, 0)) AS restored_locked,
                    GREATEST(st.away_seconds,   COALESCE(rb.best_away,   0)) AS restored_away
                FROM screen_time st
                JOIN raw_best rb
                  ON rb.agent_id = st.agent_id AND rb.record_date = st.date
                -- Only rows where the span sweep was capable of running
                WHERE EXISTS (
                    SELECT 1 FROM screen_time_spans sp
                    WHERE sp.agent_id = st.agent_id
                      AND sp.start_time::DATE = st.date
                )
                -- Only rows where raw_events has a higher value in any bucket
                AND (
                    COALESCE(rb.best_active, 0) > COALESCE(st.active_seconds, 0)
                    OR COALESCE(rb.best_idle,   0) > COALESCE(st.idle_seconds,   0)
                    OR COALESCE(rb.best_locked, 0) > COALESCE(st.locked_seconds, 0)
                    OR COALESCE(rb.best_away,   0) > COALESCE(st.away_seconds,   0)
                )
            )
            UPDATE screen_time st
            SET
                active_seconds = d.restored_active,
                idle_seconds   = d.restored_idle,
                locked_seconds = d.restored_locked,
                away_seconds   = d.restored_away,
                last_updated   = NOW(),
                updated_at     = NOW()
            FROM damaged d
            WHERE st.agent_id = d.agent_id
              AND st.date     = d.date;

            GET DIAGNOSTICS v_updated = ROW_COUNT;
            RAISE NOTICE 'Backfill complete: % screen_time row(s) restored from raw_events', v_updated;
        END $$;
    """)


def downgrade():
    # Restore the original overwrite behaviour from 20260806_screen_time_span_auth.
    op.execute("""
        CREATE OR REPLACE FUNCTION sync_screen_time_from_spans(p_date DATE DEFAULT CURRENT_DATE)
        RETURNS TABLE(ret_agent_id UUID, synced BOOLEAN) AS $$
        BEGIN
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
                idle_seconds   = EXCLUDED.idle_seconds,
                locked_seconds = EXCLUDED.locked_seconds,
                away_seconds   = EXCLUDED.away_seconds,
                last_updated   = NOW(),
                updated_at     = NOW();

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

            UPDATE screen_time_spans
            SET processed = TRUE
            WHERE start_time::DATE = p_date;

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
