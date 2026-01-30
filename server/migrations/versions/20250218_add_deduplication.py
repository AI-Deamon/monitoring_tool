"""add deduplication to switch events

Revision ID: 20250218_add_deduplication
Revises: 20250218_update_screentime_logic
Create Date: 2025-02-18 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20250218_add_deduplication'
down_revision = '20250218_update_screentime_logic'
branch_labels = None
depends_on = None


def upgrade():
    # =========================================================================
    # STEP 1: Add unique constraint to app_sessions for deduplication
    # Key: (agent_id, app, start_time) - prevents duplicate sessions
    # =========================================================================
    op.execute("""
    CREATE UNIQUE INDEX IF NOT EXISTS uq_app_sessions_agent_app_start 
    ON app_sessions (agent_id, app, start_time);
    """)
    
    # =========================================================================
    # STEP 2: Add unique constraint to domain_sessions for deduplication
    # Key: (agent_id, domain, start_time) - prevents duplicate sessions
    # =========================================================================
    op.execute("""
    CREATE UNIQUE INDEX IF NOT EXISTS uq_domain_sessions_agent_domain_start 
    ON domain_sessions (agent_id, domain, start_time);
    """)
    
    # =========================================================================
    # STEP 3: Update process_app_switch_event with deduplication
    # - Uses ON CONFLICT DO NOTHING for sessions (skip duplicates)
    # - Only increments app_usage if session was actually inserted
    # =========================================================================
    op.execute("""
    CREATE OR REPLACE FUNCTION process_app_switch_event(
        p_agent_id VARCHAR,
        p_timestamp TIMESTAMP,
        p_app VARCHAR,
        p_friendly_name VARCHAR,
        p_category VARCHAR,
        p_window_title VARCHAR,
        p_session_start TIMESTAMP,
        p_session_end TIMESTAMP,
        p_total_seconds FLOAT
    ) RETURNS TABLE(status text, message text) AS $$
    DECLARE
        v_date DATE;
        v_inserted BOOLEAN;
        v_clamped_seconds FLOAT;
    BEGIN
        v_date := p_session_start::DATE;
        v_inserted := FALSE;
        
        -- Reject NULL app name
        IF p_app IS NULL OR p_app = '' THEN
            RETURN QUERY SELECT 'skipped'::TEXT, 'NULL or empty app name'::TEXT;
            RETURN;
        END IF;

        -- Reject negative durations
        IF p_total_seconds < 0 THEN
            RETURN QUERY SELECT 'error'::TEXT, 'Negative duration rejected'::TEXT;
            RETURN;
        END IF;

        -- EXCESSIVE DURATION CHECK (> 8 hours)
        IF p_total_seconds > 28800 THEN
            RETURN QUERY SELECT 'skipped'::TEXT, 
                format('Excessive duration rejected (%s hours)', round((p_total_seconds/3600.0)::numeric, 1))::TEXT;
            RETURN;
        END IF;
        
        v_clamped_seconds := LEAST(p_total_seconds, 28800);
        
        -- 1. Try to insert into app_sessions (History)
        -- Skip if duplicate (same agent, app, start_time)
        BEGIN
            INSERT INTO app_sessions (
                agent_id, app, window_title, start_time, end_time, duration_seconds, created_at
            ) VALUES (
                p_agent_id, p_app, p_window_title, p_session_start, p_session_end, v_clamped_seconds, NOW()
            );
            v_inserted := TRUE;
        EXCEPTION WHEN unique_violation THEN
            -- Duplicate session, skip
            RETURN QUERY SELECT 'skipped'::text, 'Duplicate session ignored'::text;
            RETURN;
        END;
        
        -- 2. Only update app_usage if session was inserted (prevents double-counting)
        IF v_inserted THEN
            INSERT INTO app_usage (
                agent_id, date, app, duration_seconds, session_count, last_updated
            ) VALUES (
                p_agent_id, v_date, p_app, v_clamped_seconds::INTEGER, 1, NOW()
            )
            ON CONFLICT (agent_id, date, app) DO UPDATE SET
                duration_seconds = app_usage.duration_seconds + EXCLUDED.duration_seconds,
                session_count = app_usage.session_count + 1,
                last_updated = NOW();
        END IF;
            
        RETURN QUERY SELECT 'success'::text, 'App switch processed'::text;
    EXCEPTION WHEN OTHERS THEN
        RETURN QUERY SELECT 'error'::text, SQLERRM::text;
    END;
    $$ LANGUAGE plpgsql;
    """)

    # =========================================================================
    # STEP 4: Update process_domain_switch_event with deduplication
    # =========================================================================
    op.execute("""
    CREATE OR REPLACE FUNCTION process_domain_switch_event(
        p_agent_id VARCHAR,
        p_timestamp TIMESTAMP,
        p_domain VARCHAR,
        p_browser VARCHAR,
        p_url TEXT,
        p_session_start TIMESTAMP,
        p_session_end TIMESTAMP,
        p_total_seconds FLOAT
    ) RETURNS TABLE(status text, message text) AS $$
    DECLARE
        v_date DATE;
        v_inserted BOOLEAN;
    BEGIN
        v_date := p_session_start::DATE;
        v_inserted := FALSE;
        
        -- 1. Try to insert into domain_sessions (History)
        -- Skip if duplicate (same agent, domain, start_time)
        BEGIN
            INSERT INTO domain_sessions (
                agent_id, domain, browser, url, start_time, end_time, duration_seconds, created_at
            ) VALUES (
                p_agent_id, p_domain, p_browser, p_url, p_session_start, p_session_end, p_total_seconds, NOW()
            );
            v_inserted := TRUE;
        EXCEPTION WHEN unique_violation THEN
            -- Duplicate session, skip
            RETURN QUERY SELECT 'skipped'::text, 'Duplicate domain session ignored'::text;
            RETURN;
        END;
        
        -- 2. Only update domain_usage if session was inserted
        IF v_inserted THEN
            INSERT INTO domain_usage (
                agent_id, date, domain, browser, duration_seconds, session_count, last_updated
            ) VALUES (
                p_agent_id, v_date, p_domain, p_browser, p_total_seconds::INTEGER, 1, NOW()
            )
            ON CONFLICT (agent_id, date, domain) DO UPDATE SET
                duration_seconds = domain_usage.duration_seconds + EXCLUDED.duration_seconds,
                session_count = domain_usage.session_count + 1,
                last_updated = NOW();
        END IF;
            
        RETURN QUERY SELECT 'success'::text, 'Domain switch processed'::text;
    EXCEPTION WHEN OTHERS THEN
        RETURN QUERY SELECT 'error'::text, SQLERRM::text;
    END;
    $$ LANGUAGE plpgsql;
    """)


def downgrade():
    # Remove unique indexes
    op.execute("DROP INDEX IF EXISTS uq_app_sessions_agent_app_start;")
    op.execute("DROP INDEX IF EXISTS uq_domain_sessions_agent_domain_start;")
    
    # Restore original stored procedures (without deduplication)
    op.execute("""
    CREATE OR REPLACE FUNCTION process_app_switch_event(
        p_agent_id VARCHAR,
        p_timestamp TIMESTAMP,
        p_app VARCHAR,
        p_friendly_name VARCHAR,
        p_category VARCHAR,
        p_window_title VARCHAR,
        p_session_start TIMESTAMP,
        p_session_end TIMESTAMP,
        p_total_seconds FLOAT
    ) RETURNS TABLE(status text, message text) AS $$
    DECLARE
        v_date DATE;
    BEGIN
        v_date := p_session_start::DATE;
        
        INSERT INTO app_sessions (
            agent_id, app, window_title, start_time, end_time, duration_seconds, created_at
        ) VALUES (
            p_agent_id, p_app, p_window_title, p_session_start, p_session_end, p_total_seconds, NOW()
        );
        
        INSERT INTO app_usage (
            agent_id, date, app, duration_seconds, session_count, last_updated
        ) VALUES (
            p_agent_id, v_date, p_app, p_total_seconds::INTEGER, 1, NOW()
        )
        ON CONFLICT (agent_id, date, app) DO UPDATE SET
            duration_seconds = app_usage.duration_seconds + EXCLUDED.duration_seconds,
            session_count = app_usage.session_count + 1,
            last_updated = NOW();
            
        RETURN QUERY SELECT 'success'::text, 'App switch processed'::text;
    END;
    $$ LANGUAGE plpgsql;
    """)
    
    op.execute("""
    CREATE OR REPLACE FUNCTION process_domain_switch_event(
        p_agent_id VARCHAR,
        p_timestamp TIMESTAMP,
        p_domain VARCHAR,
        p_browser VARCHAR,
        p_url TEXT,
        p_session_start TIMESTAMP,
        p_session_end TIMESTAMP,
        p_total_seconds FLOAT
    ) RETURNS TABLE(status text, message text) AS $$
    DECLARE
        v_date DATE;
    BEGIN
        v_date := p_session_start::DATE;
        
        INSERT INTO domain_sessions (
            agent_id, domain, browser, url, start_time, end_time, duration_seconds, created_at
        ) VALUES (
            p_agent_id, p_domain, p_browser, p_url, p_session_start, p_session_end, p_total_seconds, NOW()
        );
        
        INSERT INTO domain_usage (
            agent_id, date, domain, browser, duration_seconds, session_count, last_updated
        ) VALUES (
            p_agent_id, v_date, p_domain, p_browser, p_total_seconds::INTEGER, 1, NOW()
        )
        ON CONFLICT (agent_id, date, domain) DO UPDATE SET
            duration_seconds = domain_usage.duration_seconds + EXCLUDED.duration_seconds,
            session_count = domain_usage.session_count + 1,
            last_updated = NOW();
            
        RETURN QUERY SELECT 'success'::text, 'Domain switch processed'::text;
    END;
    $$ LANGUAGE plpgsql;
    """)
