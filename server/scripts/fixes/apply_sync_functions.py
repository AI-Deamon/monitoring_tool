"""
Apply Sync Functions Patch
==========================
Run this script to add the missing sync functions to the database.
"""

import sys
import logging
from pathlib import Path
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from server_app import create_app
from extensions import db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def apply_patch():
    app = create_app()
    with app.app_context():
        logger.info("Applying stored procedures and sync functions...")
        
        # 1. Stored Procedures (for live telemetry)
        
        # process_screentime_event WITH GREATEST()
        db.session.execute(text("""
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
                    p_agent_id::UUID, v_date, p_active_total, p_idle_total, p_locked_total, NOW()
                )
                ON CONFLICT (agent_id, date) DO UPDATE SET
                    -- Use GREATEST to prevent regression if agent restarts
                    active_seconds = GREATEST(screen_time.active_seconds, EXCLUDED.active_seconds),
                    idle_seconds = GREATEST(screen_time.idle_seconds, EXCLUDED.idle_seconds),
                    locked_seconds = GREATEST(screen_time.locked_seconds, EXCLUDED.locked_seconds),
                    last_updated = NOW();
                
                RETURN QUERY SELECT 'success'::text, 'Screentime processed (total)'::text;
            EXCEPTION WHEN OTHERS THEN
                RETURN QUERY SELECT 'error'::text, SQLERRM::text;
            END;
            $$ LANGUAGE plpgsql;
        """))
        
        # process_app_switch_event (ROBUST VERSION)
        db.session.execute(text("""
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
                v_clamped_seconds FLOAT;
            BEGIN
                v_date := p_session_start::DATE;
                
                IF p_app IS NULL OR p_app = '' THEN
                    RETURN QUERY SELECT 'skipped'::TEXT, 'NULL or empty app name'::TEXT;
                    RETURN;
                END IF;

                IF p_total_seconds < 0 THEN
                    RETURN QUERY SELECT 'error'::TEXT, 'Negative duration rejected'::TEXT;
                    RETURN;
                END IF;

                IF p_total_seconds > 28800 THEN
                    RETURN QUERY SELECT 'skipped'::TEXT, 
                        format('Excessive duration rejected (%s hours)', round((p_total_seconds/3600.0)::numeric, 1))::TEXT;
                    RETURN;
                END IF;
                
                v_clamped_seconds := LEAST(p_total_seconds, 28800);
                
                -- 1. Insert into app_sessions (History)
                BEGIN
                    INSERT INTO app_sessions (
                        agent_id, app, window_title, start_time, end_time, duration_seconds, created_at
                    ) VALUES (
                        p_agent_id::UUID, p_app, p_window_title, p_session_start, p_session_end, v_clamped_seconds, NOW()
                    );
                EXCEPTION WHEN unique_violation THEN
                    RETURN QUERY SELECT 'skipped'::text, 'Duplicate session ignored'::text;
                    RETURN;
                END;
                
                -- 2. Upsert into app_usage (Daily Aggregation)
                INSERT INTO app_usage (
                    agent_id, date, app, duration_seconds, session_count, last_updated
                ) VALUES (
                    p_agent_id::UUID, v_date, p_app, v_clamped_seconds::INTEGER, 1, NOW()
                )
                ON CONFLICT (agent_id, date, app) DO UPDATE SET
                    duration_seconds = app_usage.duration_seconds + EXCLUDED.duration_seconds,
                    session_count = app_usage.session_count + 1,
                    last_updated = NOW();
                
                RETURN QUERY SELECT 'success'::text, 'App switch processed'::text;
            EXCEPTION WHEN OTHERS THEN
                RETURN QUERY SELECT 'error'::text, SQLERRM::text;
            END;
            $$ LANGUAGE plpgsql;
        """))
        
        # process_domain_switch_event
        db.session.execute(text("""
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
                
                -- 1. Insert into domain_sessions (History)
                INSERT INTO domain_sessions (
                    agent_id, domain, browser, url, start_time, end_time, duration_seconds, created_at
                ) VALUES (
                    p_agent_id::UUID, p_domain, p_browser, p_url, p_session_start, p_session_end, p_total_seconds, NOW()
                );
                
                -- 2. Upsert into domain_usage (Daily Aggregation)
                INSERT INTO domain_usage (
                    agent_id, date, domain, browser, duration_seconds, session_count, last_updated
                ) VALUES (
                    p_agent_id::UUID, v_date, p_domain, p_browser, p_total_seconds::INTEGER, 1, NOW()
                )
                ON CONFLICT (agent_id, date, domain) DO UPDATE SET
                    duration_seconds = domain_usage.duration_seconds + EXCLUDED.duration_seconds,
                    session_count = domain_usage.session_count + 1,
                    last_updated = NOW();
                
                RETURN QUERY SELECT 'success'::text, 'Domain switch processed'::text;
            EXCEPTION WHEN OTHERS THEN
                RETURN QUERY SELECT 'error'::text, SQLERRM::text;
            END;
            $$ LANGUAGE plpgsql;
        """))
        
        # 2. Sync Functions (for background thread)
        
        # sync_app_usage_from_sessions
        db.session.execute(text("""
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
        """))
        
        # sync_domain_usage_from_sessions
        db.session.execute(text("""
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
        """))
        
        # sync_screen_time_from_sessions
        # Drop first to avoid return type conflict
        db.session.execute(text("""
            DROP FUNCTION IF EXISTS sync_screen_time_from_sessions(DATE);
        """))
        
        db.session.execute(text("""
            CREATE OR REPLACE FUNCTION sync_screen_time_from_sessions(p_date DATE)
            RETURNS TABLE(out_agent_id VARCHAR, out_active_seconds INTEGER) AS $$
            DECLARE
                r RECORD;
            BEGIN
                FOR r IN
                    SELECT
                        s.agent_id,
                        COALESCE(SUM(s.duration_seconds), 0)::INTEGER as total_active
                    FROM app_sessions s
                    WHERE s.start_time::DATE = p_date
                    GROUP BY s.agent_id
                LOOP
                    -- Upsert screen_time
                    INSERT INTO screen_time (agent_id, date, active_seconds, idle_seconds, locked_seconds, last_updated)
                    VALUES (r.agent_id, p_date, r.total_active, 0, 0, NOW())
                    ON CONFLICT (agent_id, date) DO UPDATE SET
                        active_seconds = EXCLUDED.active_seconds,
                        last_updated = NOW();
                    
                    out_agent_id := r.agent_id;
                    out_active_seconds := r.total_active;
                    RETURN NEXT;
                END LOOP;
                RETURN;
            END;
            $$ LANGUAGE plpgsql;
        """))
        
        db.session.commit()
        logger.info("✅ Sync functions applied successfully with GREATEST() fix!")

if __name__ == "__main__":
    apply_patch()
