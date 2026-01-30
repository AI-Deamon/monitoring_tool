"""
Screen Time Spans Background Tasks
Add these functions and scheduler jobs to background_tasks.py
"""

# ========================================================================
# NEW FUNCTIONS - Add after audit_data_integrity()
# ========================================================================

def sync_screen_time_spans():
    """
    Aggregate screen time spans into daily totals (runs every 5 minutes).
    Processes unprocessed spans from today and yesterday.
    """
    from extensions import db
    from datetime import datetime, timedelta
    
    try:
        today = datetime.utcnow().date()
        yesterday = today - timedelta(days=1)
        
        synced_agents = set()
        
        # Process today and yesterday
        for date in [today, yesterday]:
            result = db.session.execute(text("""
                SELECT * FROM sync_screen_time_from_spans(:date)
            """), {'date': date})
            
            rows = list(result.fetchall())
            for row in rows:
                synced_agents.add(str(row[0])[:8])  # Short agent ID
        
        db.session.commit()
        
        if synced_agents:
            logger.info(f"[SYNC-SPANS] Synced {len(synced_agents)} agents")
        
    except Exception as e:
        logger.error(f"[SYNC-SPANS] Failed: {e}")
        db.session.rollback()


def check_span_processing_lag():
    """
    Alert if spans aren't being processed (runs every 15 minutes).
    Warns if unprocessed spans are > 1 hour old.
    """
    from extensions import db
    
    try:
        result = db.session.execute(text("""
            SELECT COUNT(*), MIN(created_at)
            FROM screen_time_spans
            WHERE processed = FALSE
            AND created_at < NOW() - INTERVAL '1 hour'
        """))
        
        row = result.fetchone()
        count, oldest = row[0], row[1]
        
        if count > 0:
            logger.error(
                f"[ALERT-SPANS] {count} spans unprocessed for > 1 hour. "
                f"Oldest: {oldest}"
            )
        else:
            logger.debug("[HEALTH-SPANS] All spans processed within 1 hour")
        
    except Exception as e:
        logger.error(f"[HEALTH-SPANS] Check failed: {e}")


def cleanup_old_spans():
    """
    Delete processed spans older than 7 days (runs daily).
    Returns count of deleted spans.
    """
    from extensions import db
    
    try:
        result = db.session.execute(text("""
            SELECT cleanup_old_spans()
        """))
        
        deleted_count = result.scalar()
        db.session.commit()
        
        if deleted_count > 0:
            logger.info(f"[CLEANUP-SPANS] Deleted {deleted_count} old spans")
        
    except Exception as e:
        logger.error(f"[CLEANUP-SPANS] Failed: {e}")
        db.session.rollback()


# ========================================================================
# ENHANCED SCHEDULER - Replace BackgroundScheduler class
# ========================================================================

class BackgroundScheduler:
    """Enhanced background task scheduler with interval support"""
    
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
            'last_run': None,
            'type': 'daily'
        })
    
    def add_interval_job(self, func, minutes, name):
        """Add a job to run at regular intervals"""
        self.tasks.append({
            'func': func,
            'interval_minutes': minutes,
            'name': name,
            'last_run': None,
            'type': 'interval'
        })
        
    def start(self):
        """Start the scheduler"""
        self.running = True
        self.thread = Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        logger.info("[SCHEDULER] Background tasks started (using UTC time)")
        for task in self.tasks:
            if task['type'] == 'daily':
                logger.info(f"[SCHEDULER] - {task['name']}: {task['hour']:02d}:{task['minute']:02d} UTC")
            else:
                logger.info(f"[SCHEDULER] - {task['name']}: every {task['interval_minutes']} minutes")
    
    def stop(self):
        """Stop the scheduler"""
        self.running = False
        self.shutdown_event.set()
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("[SCHEDULER] Background tasks stopped")
    
    def _run_loop(self):
        """Main scheduler loop with interval support"""
        while self.running and not self.shutdown_event.is_set():
            try:
                now = datetime.utcnow()
                
                for task in self.tasks:
                    should_run = False
                    
                    if task['type'] == 'daily':
                        # Daily task - check hour and minute
                        if now.hour == task['hour'] and now.minute == task['minute']:
                            if task['last_run'] != now.strftime('%Y-%m-%d %H:%M'):
                                task['last_run'] = now.strftime('%Y-%m-%d %H:%M')
                                should_run = True
                    
                    elif task['type'] == 'interval':
                        # Interval task - check elapsed time
                        if task['last_run'] is None:
                            # First run
                            should_run = True
                        else:
                            last_run_time = datetime.strptime(task['last_run'], '%Y-%m-%d %H:%M:%S')
                            elapsed = (now - last_run_time).total_seconds() / 60
                            if elapsed >= task['interval_minutes']:
                                should_run = True
                        
                        if should_run:
                            task['last_run'] = now.strftime('%Y-%m-%d %H:%M:%S')
                    
                    if should_run:
                        logger.info(f"[SCHEDULER] Running: {task['name']}")
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


# ========================================================================
# UPDATED start_background_tasks() - Replace existing function
# ========================================================================

def start_background_tasks(app):
    """Start background scheduler with span sync tasks"""
    scheduler = BackgroundScheduler(app)
    
    # Daily sync at 2 AM UTC
    scheduler.add_job(
        func=sync_yesterday_data,
        hour=2,
        minute=0,
        name="Daily data sync"
    )
    
    # Daily cleanup at 3 AM UTC
    scheduler.add_job(
        func=cleanup_old_data,
        hour=3,
        minute=0,
        name="Daily data cleanup"
    )
    
    # Failed event reprocessing at 4 AM UTC
    scheduler.add_job(
        func=reprocess_failed_events,
        hour=4,
        minute=0,
        name="Reprocess failed events"
    )
    
    # Data integrity audit at 5 AM UTC
    scheduler.add_job(
        func=audit_data_integrity,
        hour=5,
        minute=0,
        name="Data integrity audit"
    )
    
    # NEW: Span sync every 5 minutes
    scheduler.add_interval_job(
        func=sync_screen_time_spans,
        minutes=5,
        name="Screen time spans sync"
    )
    
    # NEW: Span health check every 15 minutes
    scheduler.add_interval_job(
        func=check_span_processing_lag,
        minutes=15,
        name="Span processing health check"
    )
    
    # NEW: Span cleanup daily at 3:30 AM UTC
    scheduler.add_job(
        func=cleanup_old_spans,
        hour=3,
        minute=30,
        name="Cleanup old spans"
    )
    
    scheduler.start()
    
    return scheduler
