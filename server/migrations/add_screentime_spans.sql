-- Screen Time Spans Migration
-- Extracted from 20260129_add_screentime_spans.py

-- ========================================================================
-- PART 1: Create screen_time_spans table
-- ========================================================================
CREATE TABLE IF NOT EXISTS screen_time_spans (
    id SERIAL PRIMARY KEY,
    span_id VARCHAR(128) UNIQUE NOT NULL,
    agent_id UUID NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
    state VARCHAR(20) NOT NULL CHECK (state IN ('active', 'idle', 'locked')),
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP NOT NULL,
    duration_seconds INTEGER NOT NULL CHECK (duration_seconds > 0 AND duration_seconds <= 86400),
    created_at TIMESTAMP DEFAULT NOW(),
    processed BOOLEAN DEFAULT FALSE,
    CONSTRAINT valid_time_range CHECK (end_time > start_time)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_spans_agent_date ON screen_time_spans(agent_id, start_time::DATE);
CREATE INDEX IF NOT EXISTS idx_spans_processed ON screen_time_spans(processed) WHERE NOT processed;
CREATE INDEX IF NOT EXISTS idx_spans_span_id ON screen_time_spans(span_id);

-- ========================================================================
-- PART 2: Aggregation stored procedure (DISABLED)
-- ========================================================================
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

-- ========================================================================
-- PART 3: Data retention cleanup function
-- ========================================================================
CREATE OR REPLACE FUNCTION cleanup_old_spans()
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM screen_time_spans
    WHERE processed = TRUE
    AND created_at < NOW() - INTERVAL '7 days';
    
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;
