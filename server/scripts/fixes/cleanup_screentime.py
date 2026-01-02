#!/usr/bin/env python3
"""
Script to clean up corrupted screen_time data.
Deletes records where total time exceeds 14 hours (clearly corrupted from double-counting).
"""
import sys
sys.path.insert(0, '/home/kali_linux/Desktop/cmon/Stable Set 1/server')

from server_main import create_app
from extensions import db

def cleanup_corrupted_screentime():
    """Delete screen_time records that are clearly corrupted (>14 hours total)."""
    
    app = create_app()
    with app.app_context():
        print('=== Cleaning Corrupted Screen Time Data ===')
        print()
        
        # 14 hours = 50400 seconds - anything more is clearly corrupted
        MAX_REASONABLE_SECONDS = 50400
        
        # Count affected records
        count_query = """
            SELECT COUNT(*) FROM screen_time 
            WHERE (COALESCE(active_seconds,0) + COALESCE(idle_seconds,0) + COALESCE(locked_seconds,0)) > %s
        """
        
        result = db.session.execute(db.text(
            "SELECT COUNT(*) FROM screen_time WHERE (COALESCE(active_seconds,0) + COALESCE(idle_seconds,0) + COALESCE(locked_seconds,0)) > :max_sec"
        ), {'max_sec': MAX_REASONABLE_SECONDS})
        
        count = result.scalar()
        print(f'Found {count} corrupted records (total > 14 hours)')
        
        if count > 0:
            # Show what will be deleted
            affected = db.session.execute(db.text("""
                SELECT agent_id, date, active_seconds, idle_seconds, locked_seconds,
                       (COALESCE(active_seconds,0) + COALESCE(idle_seconds,0) + COALESCE(locked_seconds,0)) as total
                FROM screen_time 
                WHERE (COALESCE(active_seconds,0) + COALESCE(idle_seconds,0) + COALESCE(locked_seconds,0)) > :max_sec
                ORDER BY date DESC
            """), {'max_sec': MAX_REASONABLE_SECONDS}).fetchall()
            
            print()
            print('Records to be deleted:')
            for row in affected:
                print(f"  {row[0][:8]}... | {row[1]} | active={row[2]/3600:.1f}h, idle={row[3]/3600:.1f}h, locked={row[4]/3600:.1f}h | total={row[5]/3600:.1f}h")
            
            print()
            print('Deleting corrupted records...')
            
            db.session.execute(db.text("""
                DELETE FROM screen_time 
                WHERE (COALESCE(active_seconds,0) + COALESCE(idle_seconds,0) + COALESCE(locked_seconds,0)) > :max_sec
            """), {'max_sec': MAX_REASONABLE_SECONDS})
            
            db.session.commit()
            print(f'✅ Deleted {count} corrupted records')
            print()
            print('Agents will send fresh cumulative totals within 30 seconds.')
        else:
            print('No corrupted records found.')

if __name__ == '__main__':
    cleanup_corrupted_screentime()
