-- =============================================================================
-- Migration: Add CHECK Constraints for Duration Fields (CORRECTED)
-- =============================================================================
-- Purpose: Prevent invalid duration values at the database level (Layer 3)
-- 
-- Tables: screen_time, app_usage, domain_usage, app_sessions, domain_sessions
-- =============================================================================

-- ============================================================================
-- screen_time table constraints
-- ============================================================================

ALTER TABLE screen_time 
    DROP CONSTRAINT IF EXISTS chk_active_range,
    DROP CONSTRAINT IF EXISTS chk_idle_range,
    DROP CONSTRAINT IF EXISTS chk_locked_range,
    DROP CONSTRAINT IF EXISTS chk_total_sane;

ALTER TABLE screen_time
    ADD CONSTRAINT chk_active_range 
        CHECK (active_seconds >= 0 AND active_seconds <= 86400);

ALTER TABLE screen_time
    ADD CONSTRAINT chk_idle_range 
        CHECK (idle_seconds >= 0 AND idle_seconds <= 86400);

ALTER TABLE screen_time
    ADD CONSTRAINT chk_locked_range 
        CHECK (locked_seconds >= 0 AND locked_seconds <= 86400);

ALTER TABLE screen_time
    ADD CONSTRAINT chk_total_sane 
        CHECK (active_seconds + idle_seconds + locked_seconds <= 172800);


-- ============================================================================
-- app_usage table constraints (column is duration_seconds)
-- ============================================================================

ALTER TABLE app_usage DROP CONSTRAINT IF EXISTS chk_app_usage_duration;

ALTER TABLE app_usage
    ADD CONSTRAINT chk_app_usage_duration
        CHECK (duration_seconds >= 0 AND duration_seconds <= 86400);


-- ============================================================================
-- app_sessions table constraints
-- ============================================================================

ALTER TABLE app_sessions DROP CONSTRAINT IF EXISTS chk_app_session_duration;

ALTER TABLE app_sessions
    ADD CONSTRAINT chk_app_session_duration
        CHECK (duration_seconds >= 0 AND duration_seconds <= 86400);


-- ============================================================================
-- domain_usage table constraints (column is duration_seconds)
-- ============================================================================

ALTER TABLE domain_usage DROP CONSTRAINT IF EXISTS chk_domain_usage_duration;

ALTER TABLE domain_usage
    ADD CONSTRAINT chk_domain_usage_duration
        CHECK (duration_seconds >= 0 AND duration_seconds <= 86400);


-- ============================================================================
-- domain_sessions table constraints
-- ============================================================================

ALTER TABLE domain_sessions DROP CONSTRAINT IF EXISTS chk_domain_session_duration;

ALTER TABLE domain_sessions
    ADD CONSTRAINT chk_domain_session_duration
        CHECK (duration_seconds >= 0 AND duration_seconds <= 86400);


-- ============================================================================
-- Verify constraints were added
-- ============================================================================

SELECT 
    conrelid::regclass AS table_name,
    conname AS constraint_name
FROM pg_constraint
WHERE conname LIKE 'chk_%'
ORDER BY conrelid::regclass, conname;

SELECT '✅ CHECK constraints added successfully!' AS status;
