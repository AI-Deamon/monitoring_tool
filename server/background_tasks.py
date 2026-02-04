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
    """Enhanced background task scheduler supporting daily and interval-based jobs"""
    
    def __init__(self, app):
        self.app = app
        self.running = False
        self.shutdown_event = Event()
        self.thread = None
        self.tasks = []
        
    def add_job(self, func, hour, minute, name):
        """Add a job to run at a specific time daily (UTC)"""
        self.tasks.append({
            'type': 'daily',
            'func': func,
            'hour': hour,
            'minute': minute,
            'name': name,
            'last_run': None
        })

    def add_interval_job(self, func, seconds, name):
        """Add a job to run at a fixed interval"""
        self.tasks.append({
            'type': 'interval',
            'func': func,
            'seconds': seconds,
            'name': name,
            'last_run_time': 0
        })
        
    def start(self):
        """Start the scheduler"""
        self.running = True
        self.thread = Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        logger.info("[SCHEDULER] Background tasks started")
        for task in self.tasks:
            if task['type'] == 'daily':
                logger.info(f"[SCHEDULER] - {task['name']}: Daily {task['hour']:02d}:{task['minute']:02d} UTC")
            else:
                logger.info(f"[SCHEDULER] - {task['name']}: Every {task['seconds']}s")
    
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
                now = datetime.utcnow()
                now_ts = time.time()
                
                for task in self.tasks:
                    should_run = False
                    
                    if task['type'] == 'daily':
                        if now.hour == task['hour'] and now.minute == task['minute']:
                            if task['last_run'] != now.strftime('%Y-%m-%d %H:%M'):
                                should_run = True
                                task['last_run'] = now.strftime('%Y-%m-%d %H:%M')
                    
                    elif task['type'] == 'interval':
                        if now_ts - task['last_run_time'] >= task['seconds']:
                            should_run = True
                            task['last_run_time'] = now_ts

                    if should_run:
                        logger.info(f"[SCHEDULER] Running: {task['name']}")
                        try:
                            with self.app.app_context():
                                task['func']()
                        except Exception as e:
                            logger.error(f"[SCHEDULER] Error in {task['name']}: {e}")
                
                # Sleep for 10 seconds (more responsive than 30s)
                self.shutdown_event.wait(10)
                
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


def reprocess_failed_events():
    """
    Reprocess failed RawEvents that were stored but not processed.
    
    This handles recovery from transient failures (e.g., DB locks, timeouts).
    Events are retried up to 3 times before being marked as permanently failed.
    """
    from extensions import db
    import server_models
    import json
    
    try:
        # Get failed events from last 24 hours (avoid retrying ancient failures)
        from datetime import datetime, timedelta
        cutoff = datetime.utcnow() - timedelta(hours=24)
        
        failed_events = server_models.RawEvent.query.filter(
            server_models.RawEvent.processed == False,
            server_models.RawEvent.received_at >= cutoff,
            server_models.RawEvent.error.isnot(None)
        ).limit(50).all()
        
        if not failed_events:
            return
            
        logger.info(f"[REPROCESS] Found {len(failed_events)} failed events to retry")
        
        success_count = 0
        for event in failed_events:
            try:
                payload = json.loads(event.payload) if isinstance(event.payload, str) else event.payload
                
                # Retry based on event type
                if event.event_type == 'screentime' or event.event_type == 'state_duration':
                    # Parse and call authoritative handler (Additive logic)
                    from server_telemetry import handle_state_duration
                    # Convert raw event back to payload for handler
                    res = handle_state_duration(event.agent_id, payload)
                    if res.status_code == 200:
                        event.processed = True
                        event.error = None
                        success_count += 1
                        
                elif event.event_type == 'app-switch':
                    result = db.session.execute(text("""
                        SELECT * FROM process_app_switch_event(
                            :agent_id, :timestamp, :app, :friendly_name, :category,
                            :window_title, :session_start, :session_end, :total_seconds
                        )
                    """), {
                        'agent_id': event.agent_id,
                        'timestamp': event.received_at,
                        'app': payload.get('app', ''),
                        'friendly_name': payload.get('friendly_name', ''),
                        'category': payload.get('category', 'other'),
                        'window_title': payload.get('window_title', ''),
                        'session_start': payload.get('session_start'),
                        'session_end': payload.get('session_end'),
                        'total_seconds': payload.get('total_seconds', 0)
                    })
                    row = result.fetchone()
                    if row and row[0] == 'success':
                        event.processed = True
                        event.error = None
                        success_count += 1
                        
            except Exception as e:
                # Update error message but don't spam logs
                event.error = f"Retry failed: {str(e)[:200]}"
                
        db.session.commit()
        logger.info(f"[REPROCESS] Successfully reprocessed {success_count}/{len(failed_events)} events")
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"[REPROCESS] Error during reprocessing: {e}")


def audit_data_integrity():
    """
    Audit data integrity by comparing screen_time totals with app_sessions sums.
    
    Logs warnings if discrepancies exceed threshold (allows for timing differences).
    """
    from extensions import db
    import server_models
    
    try:
        today = datetime.utcnow().date()
        
        # Get screen_time totals
        screen_times = server_models.ScreenTime.query.filter_by(date=today).all()
        
        discrepancies = []
        for st in screen_times:
            # Get sum of app sessions for this agent today
            result = db.session.execute(text("""
                SELECT COALESCE(SUM(duration_seconds), 0) as total
                FROM app_sessions
                WHERE agent_id = :agent_id
                AND start_time::DATE = :date
            """), {'agent_id': st.agent_id, 'date': today})
            
            row = result.fetchone()
            session_total = row[0] if row else 0
            
            # Compare active_seconds with session total
            # Allow 10% or 60 seconds tolerance (whichever is greater)
            threshold = max(st.active_seconds * 0.1, 60)
            diff = abs(st.active_seconds - session_total)
            
            if diff > threshold and st.active_seconds > 0:
                discrepancies.append({
                    'agent_id': st.agent_id[:12] + '...',
                    'screen_time_active': st.active_seconds,
                    'session_total': session_total,
                    'difference': diff
                })
        
        if discrepancies:
            logger.warning(f"[AUDIT] Found {len(discrepancies)} data discrepancies:")
            for d in discrepancies[:5]:  # Log first 5
                logger.warning(
                    f"[AUDIT] Agent {d['agent_id']}: "
                    f"screen_time={d['screen_time_active']}s vs sessions={d['session_total']}s "
                    f"(diff={d['difference']}s)"
                )
        else:
            logger.info("[AUDIT] Data integrity check passed - no significant discrepancies")
            
    except Exception as e:
        logger.error(f"[AUDIT] Error during audit: {e}")


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
    
    # Run failed event reprocessing at 4 AM UTC
    scheduler.add_job(
        func=reprocess_failed_events,
        hour=4,
        minute=0,
        name="Reprocess failed events"
    )
    
    # Run data integrity audit at 5 AM UTC
    scheduler.add_job(
        func=audit_data_integrity,
        hour=5,
        minute=0,
        name="Data integrity audit"
    )
    
    scheduler.start()
    
    return scheduler
