-- Migration: Session Sync Functions
-- Creates functions to aggregate session data into daily totals

-- Function 1: sync_app_usage_from_sessions
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

-- Function 2: sync_domain_usage_from_sessions
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

-- Function 3: sync_screen_time_from_sessions (DISABLED)
-- 
-- ❌ DISABLED: This function is now a NO-OP to prevent session aggregation
-- 
-- REASON: Screen time is now agent-authoritative only.
-- The agent's state_machine.py is the ONLY place that calculates time.
-- Sessions are for app/domain usage tracking, NOT for screen time aggregation.
-- 
-- CRITICAL: Server MUST NOT attempt to reconstruct or repair screen time gaps.
-- Under-counting is acceptable; fabricated time is forbidden.
CREATE OR REPLACE FUNCTION sync_screen_time_from_sessions(p_date DATE)
RETURNS TABLE(agent_id VARCHAR, active_seconds INTEGER) AS $$
BEGIN
    -- This function intentionally does nothing
    -- Screen time is now agent-authoritative only
    RETURN;
END;
$$ LANGUAGE plpgsql;
