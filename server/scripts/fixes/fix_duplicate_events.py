"""
Fix Duplicate Events - Hotfix Script
=====================================
Run this script to add deduplication to app-switch and domain-switch events.

PROBLEM:
    If agent sends same event twice (network retry), server would:
    - Create duplicate session row
    - Double-count in daily totals (app_usage, domain_usage)

SOLUTION:
    - Add unique index on (agent_id, app/domain, start_time)
    - Update stored procedures to skip duplicates
    - Only increment daily totals if session was actually inserted

Usage:
    cd c:/tmp/server
    python fix_duplicate_events.py
"""
import sys
import logging
from pathlib import Path
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).parent))

from server_app import create_app
from extensions import db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def apply_fix():
    app = create_app()
    with app.app_context():
        logger.info("=" * 60)
        logger.info("ADDING DEDUPLICATION TO SWITCH EVENTS")
        logger.info("=" * 60)
        
        try:
            # Step 1: Add unique indexes
            logger.info("\n[1/4] Adding unique index to app_sessions...")
            db.session.execute(text("""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_app_sessions_agent_app_start 
                ON app_sessions (agent_id, app, start_time);
            """))
            
            logger.info("[2/4] Adding unique index to domain_sessions...")
            db.session.execute(text("""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_domain_sessions_agent_domain_start 
                ON domain_sessions (agent_id, domain, start_time);
            """))
            
            # Step 2: Update app_switch stored procedure
            logger.info("[3/4] Updating process_app_switch_event...")
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
                v_inserted BOOLEAN;
            BEGIN
                v_date := p_session_start::DATE;
                v_inserted := FALSE;
                
                -- 1. Try to insert into app_sessions (History)
                -- Skip if duplicate (same agent, app, start_time)
                BEGIN
                    INSERT INTO app_sessions (
                        agent_id, app, window_title, start_time, end_time, duration_seconds, created_at
                    ) VALUES (
                        p_agent_id, p_app, p_window_title, p_session_start, p_session_end, p_total_seconds, NOW()
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
                        p_agent_id, v_date, p_app, p_total_seconds::INTEGER, 1, NOW()
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
            """))
            
            # Step 3: Update domain_switch stored procedure
            logger.info("[4/4] Updating process_domain_switch_event...")
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
            """))
            
            db.session.commit()
            
            logger.info("")
            logger.info("[SUCCESS] Deduplication added!")
            logger.info("")
            logger.info("Now if the same event is sent twice:")
            logger.info("  - First time: Session inserted + daily totals updated")
            logger.info("  - Second time: Skipped (duplicate detected)")
            logger.info("")
            logger.info("=" * 60)
            
            return True
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"[ERROR] Failed to apply fix: {e}")
            return False

if __name__ == "__main__":
    success = apply_fix()
    sys.exit(0 if success else 1)
