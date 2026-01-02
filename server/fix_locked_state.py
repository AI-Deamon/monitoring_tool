"""
Fix Locked State Detection - Database Migration Script (PostgreSQL)
Reclassifies lockapp.exe sessions as "locked" state retroactively.

Run this script once after deploying the server code fixes.

Usage:
    cd server
    python fix_locked_state.py
"""
import os
import sys
from datetime import datetime

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("Note: python-dotenv not installed, using environment variables directly")

# Apps that indicate locked screen
LOCK_APPS = ['lockapp.exe', 'logonui.exe', 'winlogon.exe']

def fix_locked_states():
    """Fix locked state detection in existing database records (PostgreSQL)."""
    
    database_url = os.getenv('DATABASE_URL')
    
    if not database_url:
        print("ERROR: DATABASE_URL not set in environment or .env file")
        print("Make sure .env file exists in the server directory")
        return
    
    print(f"Database URL: {database_url[:50]}...")
    
    try:
        import psycopg2
        from psycopg2 import sql
    except ImportError:
        print("ERROR: psycopg2 not installed. Run: pip install psycopg2-binary")
        return
    
    try:
        conn = psycopg2.connect(database_url)
        cursor = conn.cursor()
        print("Connected to PostgreSQL database!")
    except Exception as e:
        print(f"ERROR: Could not connect to database: {e}")
        return
    
    changes_made = 0
    
    # ================================================================
    # Fix 1: Check for lock screen app sessions
    # ================================================================
    print("\n[1/3] Checking app_sessions for lock screen apps...")
    
    try:
        cursor.execute("""
            SELECT COUNT(*) FROM app_sessions 
            WHERE LOWER(app) IN ('lockapp.exe', 'logonui.exe', 'winlogon.exe')
        """)
        lock_sessions = cursor.fetchone()[0]
        print(f"     Found {lock_sessions} sessions with lock screen apps")
    except Exception as e:
        print(f"     Skipped (table may not exist): {e}")
    
    # ================================================================
    # Fix 2: Update agent_current_status - Fix current state
    # ================================================================
    print("\n[2/3] Updating agent_current_status for locked apps...")
    
    try:
        cursor.execute("""
            UPDATE agent_current_status 
            SET current_state = 'locked'
            WHERE LOWER(current_app) IN ('lockapp.exe', 'logonui.exe', 'winlogon.exe')
            AND (current_state IS NULL OR current_state != 'locked')
        """)
        status_updates = cursor.rowcount
        print(f"     Updated {status_updates} agent status records to 'locked'")
        changes_made += status_updates
    except Exception as e:
        print(f"     Skipped (table may not exist): {e}")
    
    # ================================================================
    # Fix 3: Calculate locked time from app_sessions and add to screen_time
    # ================================================================
    print("\n[3/3] Calculating locked time from app_sessions...")
    
    try:
        cursor.execute("""
            SELECT agent_id, DATE(start_time) as usage_date, SUM(duration_seconds) as locked_duration
            FROM app_sessions
            WHERE LOWER(app) IN ('lockapp.exe', 'logonui.exe', 'winlogon.exe')
            GROUP BY agent_id, DATE(start_time)
        """)
        
        locked_by_day = cursor.fetchall()
        print(f"     Found locked time for {len(locked_by_day)} agent-days")
        
        for agent_id, usage_date, locked_duration in locked_by_day:
            if locked_duration and locked_duration > 0:
                # Update screen_time record
                cursor.execute("""
                    UPDATE screen_time 
                    SET locked_seconds = COALESCE(locked_seconds, 0) + %s
                    WHERE agent_id = %s AND date = %s
                """, (locked_duration, agent_id, usage_date))
                
                if cursor.rowcount > 0:
                    print(f"     {agent_id} on {usage_date}: +{locked_duration}s locked time")
                    changes_made += 1
    except Exception as e:
        print(f"     Skipped (table may not exist): {e}")
    
    # Commit all changes
    conn.commit()
    print(f"\n{'='*60}")
    print(f"DONE! Made {changes_made} database changes.")
    print(f"{'='*60}")
    
    # Show current screen_time summary
    print("\nCurrent screen_time summary (today):")
    try:
        cursor.execute("""
            SELECT agent_id, date, active_seconds, idle_seconds, locked_seconds
            FROM screen_time
            WHERE date = CURRENT_DATE
            ORDER BY agent_id
        """)
        
        rows = cursor.fetchall()
        if rows:
            for row in rows:
                agent_id, date, active, idle, locked = row
                print(f"  {agent_id}: Active={active or 0}s, Idle={idle or 0}s, Locked={locked or 0}s")
        else:
            print("  No screen_time records for today yet.")
    except Exception as e:
        print(f"  Could not fetch summary: {e}")
    
    cursor.close()
    conn.close()
    print("\nDatabase connection closed.")
    print("\nNOTE: Restart the server for the code changes to take effect.")


if __name__ == '__main__':
    fix_locked_states()
