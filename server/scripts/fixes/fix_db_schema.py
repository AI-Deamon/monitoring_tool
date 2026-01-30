"""
Fix Database Schema Script
==========================
Run this script to add missing columns and fix stored procedures.
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

def fix_schema():
    app = create_app()
    with app.app_context():
        logger.info("=" * 60)
        logger.info("Fixing database schema...")
        logger.info("=" * 60)
        
        # 1. Add missing columns to agent_current_status table
        logger.info("[1/3] Adding missing columns to agent_current_status...")
        
        try:
            # Check if columns exist and add them if not
            db.session.execute(text("""
            DO $$
            BEGIN
                -- Add domain_session_start column if it doesn't exist
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns 
                    WHERE table_name = 'agent_current_status' 
                    AND column_name = 'domain_session_start'
                ) THEN
                    ALTER TABLE agent_current_status 
                    ADD COLUMN domain_session_start TIMESTAMP NULL;
                    RAISE NOTICE 'Added column: domain_session_start';
                END IF;
                
                -- Add domain_duration_seconds column if it doesn't exist
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns 
                    WHERE table_name = 'agent_current_status' 
                    AND column_name = 'domain_duration_seconds'
                ) THEN
                    ALTER TABLE agent_current_status 
                    ADD COLUMN domain_duration_seconds INTEGER DEFAULT 0;
                    RAISE NOTICE 'Added column: domain_duration_seconds';
                END IF;
                
                -- Add current_domain column if it doesn't exist
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns 
                    WHERE table_name = 'agent_current_status' 
                    AND column_name = 'current_domain'
                ) THEN
                    ALTER TABLE agent_current_status 
                    ADD COLUMN current_domain VARCHAR(255) NULL;
                    RAISE NOTICE 'Added column: current_domain';
                END IF;
                
                -- Add current_browser column if it doesn't exist
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns 
                    WHERE table_name = 'agent_current_status' 
                    AND column_name = 'current_browser'
                ) THEN
                    ALTER TABLE agent_current_status 
                    ADD COLUMN current_browser VARCHAR(100) NULL;
                    RAISE NOTICE 'Added column: current_browser';
                END IF;
                
                -- Add current_url column if it doesn't exist
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns 
                    WHERE table_name = 'agent_current_status' 
                    AND column_name = 'current_url'
                ) THEN
                    ALTER TABLE agent_current_status 
                    ADD COLUMN current_url TEXT NULL;
                    RAISE NOTICE 'Added column: current_url';
                END IF;
            END
            $$;
            """))
            db.session.commit()
            logger.info("[OK] Agent current status columns added/verified")
        except Exception as e:
            db.session.rollback()
            logger.error(f"[ERROR] Failed to add columns: {e}")
            raise
        
        # 2. Fix the sync_screen_time_from_sessions function with proper variable naming
        logger.info("[2/3] Fixing sync_screen_time_from_sessions function...")
        
        try:
            # First drop the old function to avoid return type conflicts
            db.session.execute(text("""
            DROP FUNCTION IF EXISTS sync_screen_time_from_sessions(DATE);
            """))
            
            db.session.execute(text("""
            CREATE OR REPLACE FUNCTION sync_screen_time_from_sessions(p_date DATE)
            RETURNS TABLE(out_agent_id VARCHAR, out_active_seconds INTEGER) AS $$
            DECLARE
                rec RECORD;
            BEGIN
                FOR rec IN 
                    SELECT 
                        s.agent_id AS agg_agent_id,
                        COALESCE(SUM(s.duration_seconds), 0)::INTEGER as total_active
                    FROM app_sessions s
                    WHERE s.start_time::DATE = p_date
                    GROUP BY s.agent_id
                LOOP
                    -- Upsert screen_time using qualified column names
                    INSERT INTO screen_time (agent_id, date, active_seconds, idle_seconds, locked_seconds, last_updated)
                    VALUES (rec.agg_agent_id, p_date, rec.total_active, 0, 0, NOW())
                    ON CONFLICT (agent_id, date) DO UPDATE SET
                        active_seconds = EXCLUDED.active_seconds,
                        last_updated = NOW();
                        
                    out_agent_id := rec.agg_agent_id;
                    out_active_seconds := rec.total_active;
                    RETURN NEXT;
                END LOOP;
                RETURN;
            END;
            $$ LANGUAGE plpgsql;
            """))
            db.session.commit()
            logger.info("[OK] sync_screen_time_from_sessions function fixed")
        except Exception as e:
            db.session.rollback()
            logger.error(f"[ERROR] Failed to fix function: {e}")
            raise
        
        # 3. Re-apply all stored procedures for good measure
        logger.info("[3/3] Re-applying all stored procedures...")
        
        try:
            # process_screentime_event
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

            # process_app_switch_event
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
            BEGIN
                v_date := p_session_start::DATE;
                
                INSERT INTO app_sessions (
                    agent_id, app, window_title, start_time, end_time, duration_seconds, created_at
                ) VALUES (
                    p_agent_id::UUID, p_app, p_window_title, p_session_start, p_session_end, p_total_seconds, NOW()
                );
                
                INSERT INTO app_usage (
                    agent_id, date, app, duration_seconds, session_count, last_updated
                ) VALUES (
                    p_agent_id::UUID, v_date, p_app, p_total_seconds::INTEGER, 1, NOW()
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
                
                INSERT INTO domain_sessions (
                    agent_id, domain, browser, url, start_time, end_time, duration_seconds, created_at
                ) VALUES (
                    p_agent_id::UUID, p_domain, p_browser, p_url, p_session_start, p_session_end, p_total_seconds, NOW()
                );
                
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

            # sync_app_usage_from_sessions
            db.session.execute(text("""
            CREATE OR REPLACE FUNCTION sync_app_usage_from_sessions(p_date DATE)
            RETURNS void AS $$
            BEGIN
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
            
            db.session.commit()
            logger.info("[OK] All stored procedures re-applied")
        except Exception as e:
            db.session.rollback()
            logger.error(f"[ERROR] Failed to re-apply stored procedures: {e}")
            raise
        
        logger.info("=" * 60)
        logger.info("[SUCCESS] Database schema fixed!")
        logger.info("Please restart the server for changes to take effect.")
        logger.info("=" * 60)

if __name__ == "__main__":
    fix_schema()
