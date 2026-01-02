"""
Fix Screen Time Logic - Hotfix Script
======================================
Run this script to update the stored procedure to use REPLACE logic.

PROBLEM:
    Agent sends cumulative daily totals (e.g., active=450)
    Old server ADDED these, causing inflated values

SOLUTION:
    Server now uses GREATEST() to store the agent's totals directly
    This prevents regression if agent restarts mid-day

Usage:
    cd c:/tmp/server
    python fix_screentime_logic.py
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

SCREENTIME_FUNCTION = """
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
        p_agent_id, v_date, p_active_total, p_idle_total, p_locked_total, NOW()
    )
    ON CONFLICT (agent_id, date) DO UPDATE SET
        -- Replace with new total from agent using GREATEST (Source of Truth)
        -- GREATEST prevents regression if agent restarts and sends smaller values
        active_seconds = GREATEST(screen_time.active_seconds, EXCLUDED.active_seconds),
        idle_seconds = GREATEST(screen_time.idle_seconds, EXCLUDED.idle_seconds),
        locked_seconds = GREATEST(screen_time.locked_seconds, EXCLUDED.locked_seconds),
        last_updated = NOW();
        
    RETURN QUERY SELECT 'success'::text, 'Screentime processed (daily total)'::text;
EXCEPTION WHEN OTHERS THEN
    RETURN QUERY SELECT 'error'::text, SQLERRM::text;
END;
$$ LANGUAGE plpgsql;
"""

def apply_fix():
    app = create_app()
    with app.app_context():
        logger.info("=" * 60)
        logger.info("FIXING SCREEN TIME LOGIC")
        logger.info("=" * 60)
        logger.info("")
        logger.info("BEFORE: Server ADDED agent values (causing inflation)")
        logger.info("AFTER:  Server uses GREATEST() to store daily totals")
        logger.info("")
        
        try:
            # Apply the updated stored procedure
            db.session.execute(text(SCREENTIME_FUNCTION))
            db.session.commit()
            
            logger.info("[SUCCESS] Stored procedure updated!")
            logger.info("")
            logger.info("The process_screentime_event function now:")
            logger.info("  1. Receives daily cumulative totals from agent")
            logger.info("  2. Uses GREATEST() to prevent regression on restart")
            logger.info("  3. Stores values directly (no more addition)")
            logger.info("")
            logger.info("=" * 60)
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"[ERROR] Failed to apply fix: {e}")
            return False
    
    return True

if __name__ == "__main__":
    success = apply_fix()
    sys.exit(0 if success else 1)
