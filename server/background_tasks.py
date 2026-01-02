"""
Background Tasks - Daily Sync
==============================
Runs sync functions to ensure data integrity.
"""

import logging
from datetime import datetime, timedelta
from threading import Thread, Event
import time
from sqlalchemy import text

logger = logging.getLogger(__name__)

class BackgroundScheduler:
    """Simple background task scheduler"""
    
    def __init__(self, app):
        self.app = app
        self.running = False
        self.shutdown_event = Event()
        self.thread = None
        self.tasks = []
        
    def add_job(self, func, hour, minute, name):
        """Add a job to run at a specific time daily (UTC)"""
        self.tasks.append({
            'func': func,
            'hour': hour,
            'minute': minute,
            'name': name,
            'last_run': None
        })
        
    def start(self):
        """Start the scheduler"""
        self.running = True
        self.thread = Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        logger.info("[SCHEDULER] Background tasks started (using UTC time)")
        for task in self.tasks:
            logger.info(f"[SCHEDULER] - {task['name']}: {task['hour']:02d}:{task['minute']:02d} UTC")
    
    def stop(self):
        """Stop the scheduler"""
        self.running = False
        self.shutdown_event.set()
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("[SCHEDULER] Background tasks stopped")
    
    def _run_loop(self):
        """Main scheduler loop"""
        while self.running and not self.shutdown_event.is_set():
            try:
                # Bug #6 Fix: Use UTC time consistently to prevent DST issues
                now = datetime.utcnow()
                
                for task in self.tasks:
                    # Check if it's time to run (using UTC hours/minutes)
                    if now.hour == task['hour'] and now.minute == task['minute']:
                        # Only run once per minute
                        if task['last_run'] != now.strftime('%Y-%m-%d %H:%M'):
                            task['last_run'] = now.strftime('%Y-%m-%d %H:%M')
                            logger.info(f"[SCHEDULER] Running: {task['name']} (UTC {now.hour:02d}:{now.minute:02d})")
                            try:
                                with self.app.app_context():
                                    task['func']()
                            except Exception as e:
                                logger.error(f"[SCHEDULER] Error in {task['name']}: {e}")
                
                # Sleep for 30 seconds before checking again
                self.shutdown_event.wait(30)
                
            except Exception as e:
                logger.error(f"[SCHEDULER] Error in scheduler loop: {e}")
                self.shutdown_event.wait(60)


def sync_yesterday_data():
    """Sync yesterday's data to ensure aggregations are correct"""
    from extensions import db
    
    yesterday = (datetime.utcnow() - timedelta(days=1)).date()
    
    try:
        logger.info(f"[SYNC] Running daily sync for {yesterday}")
        
        # Sync app usage from sessions
        db.session.execute(text("""
            SELECT sync_app_usage_from_sessions(:date)
        """), {'date': yesterday})
        logger.info("[SYNC] [OK] App usage synced")
        
        # Sync domain usage from sessions
        db.session.execute(text("""
            SELECT sync_domain_usage_from_sessions(:date)
        """), {'date': yesterday})
        logger.info("[SYNC] [OK] Domain usage synced")
        
        # Sync screen time from sessions
        result = db.session.execute(text("""
            SELECT * FROM sync_screen_time_from_sessions(:date)
        """), {'date': yesterday})
        
        rows = result.fetchall()
        logger.info(f"[SYNC] [OK] Screen time synced for {len(rows)} agents")
        
        db.session.commit()
        logger.info(f"[SYNC] Daily sync completed successfully")
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"[SYNC] Error during daily sync: {e}")


def cleanup_old_data():
    """Run cleanup script for data retention"""
    # Bug #12 Fix: Separate import check from execution
    try:
        from server_cleanup import cleanup_old_data as do_cleanup
    except ImportError:
        logger.error("[CLEANUP] server_cleanup.py not found - cleanup disabled!")
        return
    
    try:
        logger.info("[CLEANUP] Starting data retention cleanup...")
        do_cleanup()
        logger.info("[CLEANUP] Cleanup completed")
    except Exception as e:
        logger.error(f"[CLEANUP] Cleanup failed: {e}", exc_info=True)


def start_background_tasks(app):
    """Start background scheduler"""
    scheduler = BackgroundScheduler(app)
    
    # Run daily sync at 2 AM UTC (7:30 AM IST)
    scheduler.add_job(
        func=sync_yesterday_data,
        hour=2,
        minute=0,
        name="Daily data sync"
    )
    
    # Run cleanup at 3 AM UTC (8:30 AM IST)
    scheduler.add_job(
        func=cleanup_old_data,
        hour=3,
        minute=0,
        name="Daily data cleanup"
    )
    
    scheduler.start()
    
    return scheduler
