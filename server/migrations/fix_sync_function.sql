-- Fix Sync Function - Ambiguous Column Error
-- This file fixes the column ambiguity error in sync_screen_time_from_spans
-- 
-- ❌ DISABLED: This function is now a NO-OP to prevent span aggregation
-- 
-- REASON: Screen time is now agent-authoritative only.
-- The agent's state_machine.py is the ONLY place that calculates time.
-- Spans are for timeline visualization only, NOT for aggregation.
-- 
-- CRITICAL: Server MUST NOT attempt to reconstruct or repair screen time gaps.
-- Under-counting is acceptable; fabricated time is forbidden.

CREATE OR REPLACE FUNCTION sync_screen_time_from_spans(p_date DATE DEFAULT CURRENT_DATE)
RETURNS TABLE(ret_agent_id UUID, synced BOOLEAN) AS $$
BEGIN
    -- This function intentionally does nothing
    -- Screen time is now agent-authoritative only
    -- Spans are for timeline visualization only
    RETURN;
END;
$$ LANGUAGE plpgsql;
