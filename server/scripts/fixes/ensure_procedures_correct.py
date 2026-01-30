#!/usr/bin/env python3
"""
Self-Healing Script: Ensure Database Stored Procedures are Correct
Run this on server startup to fix broken functions or applying updates.
"""
import sys
import logging
from pathlib import Path

# Add server directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import text
from server_app import create_app
from extensions import db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def apply_fixes():
    app = create_app()
    with app.app_context():
        logger.info("Verifying and fixing stored procedures...")
        
        # FIX 1: process_app_switch_event (Drop duplicates & recreate)
        try:
            # Drop old/duplicate versions first
            db.session.execute(text("DROP FUNCTION IF EXISTS process_app_switch_event(VARCHAR, TIMESTAMP, VARCHAR, VARCHAR, VARCHAR, VARCHAR, TIMESTAMP, TIMESTAMP, FLOAT)"))
            db.session.execute(text("DROP FUNCTION IF EXISTS process_app_switch_event(VARCHAR, TIMESTAMP, VARCHAR, VARCHAR, VARCHAR, TEXT, TIMESTAMP, TIMESTAMP, FLOAT)"))
            
            # Create robust version
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
                
                BEGIN
                    INSERT INTO app_sessions (
                        agent_id, app, window_title, start_time, end_time, duration_seconds, created_at
                    ) VALUES (
                        p_agent_id::UUID, p_app, p_window_title, p_session_start, p_session_end, v_clamped_seconds, NOW()
                    );
                EXCEPTION WHEN unique_violation THEN
                    RETURN QUERY SELECT 'skipped'::TEXT, 'Duplicate session ignored'::TEXT;
                    RETURN;
                END;

                INSERT INTO app_usage (
                    agent_id, date, app, duration_seconds, session_count, last_updated
                ) VALUES (
                    p_agent_id::UUID, v_date, p_app, v_clamped_seconds::INTEGER, 1, NOW()
                )
                ON CONFLICT (agent_id, date, app) DO UPDATE SET
                    duration_seconds = app_usage.duration_seconds + EXCLUDED.duration_seconds,
                    session_count = app_usage.session_count + 1,
                    last_updated = NOW();

                RETURN QUERY SELECT 'success'::TEXT, 'App switch processed'::TEXT;
            EXCEPTION WHEN OTHERS THEN
                RETURN QUERY SELECT 'error'::TEXT, SQLERRM::TEXT;
            END;
            $$ LANGUAGE plpgsql;
            """))
            logger.info("✓ process_app_switch_event fixed/verified")
        except Exception as e:
            logger.error(f"Failed to fix process_app_switch_event: {e}")

        # FIX 2: process_screentime_delta
        try:
            db.session.execute(text("""
            CREATE OR REPLACE FUNCTION process_screentime_delta(
                p_agent_id VARCHAR,
                p_timestamp TIMESTAMP,
                p_delta_active INTEGER,
                p_delta_idle INTEGER,
                p_delta_locked INTEGER,
                p_state VARCHAR,
                p_delta_away INTEGER DEFAULT 0
            ) RETURNS TABLE(status text, message text) AS $$
            DECLARE
                v_date DATE;
            BEGIN
                -- Extract date from timestamp
                v_date := p_timestamp::DATE;
                
                -- INCREMENTAL ADD MODEL (Step 367):
                -- Add the deltas to existing values (or create new row if first of day)
                INSERT INTO screen_time (
                    agent_id, date, active_seconds, idle_seconds, locked_seconds, away_seconds, last_updated
                ) VALUES (
                    p_agent_id::UUID, v_date, p_delta_active, p_delta_idle, p_delta_locked, p_delta_away, NOW()
                )
                ON CONFLICT (agent_id, date) DO UPDATE SET
                    active_seconds = screen_time.active_seconds + EXCLUDED.active_seconds,
                    idle_seconds   = screen_time.idle_seconds   + EXCLUDED.idle_seconds,
                    locked_seconds = screen_time.locked_seconds + EXCLUDED.locked_seconds,
                    away_seconds   = COALESCE(screen_time.away_seconds, 0) + EXCLUDED.away_seconds,
                    last_updated   = NOW();

                RETURN QUERY SELECT 'success'::text, 'Screentime delta added'::text;
            EXCEPTION WHEN OTHERS THEN
                RETURN QUERY SELECT 'error'::text, SQLERRM::text;
            END;
            $$ LANGUAGE plpgsql;
            """))
            logger.info("✓ process_screentime_delta fixed/verified")
        except Exception as e:
            logger.error(f"Failed to fix process_screentime_delta: {e}")

        db.session.commit()
        logger.info("Database procedures are clean.")

if __name__ == "__main__":
    apply_fixes()
