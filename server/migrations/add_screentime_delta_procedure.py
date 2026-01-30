#!/usr/bin/env python3
"""
Migration: Add process_screentime_delta stored procedure

This creates a new stored procedure that uses INCREMENTAL ADD model
instead of GREATEST (replace) model.

Run this AFTER deploying the new agent code with delta fields.
Old agents will continue to use the legacy process_screentime_event().
"""

import sys
from pathlib import Path

# Add server directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from flask import Flask
from extensions import db
from sqlalchemy import text


def create_delta_procedure():
    """Create the process_screentime_delta stored procedure."""
    
    print("=" * 70)
    print("Creating process_screentime_delta stored procedure...")
    print("=" * 70)
    
    # Import and create app context
    from server_app import create_app
    app = create_app()
    
    with app.app_context():
        try:
            # Create the new stored procedure
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
                
                -- INCREMENTAL ADD MODEL:
                -- Add the deltas to existing values (or create new row if first of day)
                INSERT INTO screen_time (
                    agent_id, date, active_seconds, idle_seconds, locked_seconds, away_seconds, last_updated
                ) VALUES (
                    p_agent_id, v_date, p_delta_active, p_delta_idle, p_delta_locked, p_delta_away, NOW()
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
            
            db.session.commit()
            print("✓ process_screentime_delta created successfully!")
            print("")
            print("This procedure uses INCREMENTAL ADD model:")
            print("  - Agent sends delta values (e.g., +30s since last heartbeat)")
            print("  - Server ADDS deltas to existing totals")
            print("  - No data loss on agent restart")
            print("")
            print("The legacy process_screentime_event() still works for old agents.")
            
        except Exception as e:
            db.session.rollback()
            print(f"✗ Error creating procedure: {e}")
            raise


def verify_procedure():
    """Verify the procedure was created correctly."""
    
    from server_app import create_app
    app = create_app()
    
    with app.app_context():
        result = db.session.execute(text("""
            SELECT proname, prosrc 
            FROM pg_proc 
            WHERE proname = 'process_screentime_delta'
        """))
        
        row = result.fetchone()
        if row:
            print("")
            print("✓ Verification: process_screentime_delta exists in database")
            return True
        else:
            print("")
            print("✗ Verification FAILED: procedure not found")
            return False


if __name__ == "__main__":
    create_delta_procedure()
    verify_procedure()
    print("")
    print("=" * 70)
    print("Migration complete!")
    print("=" * 70)
