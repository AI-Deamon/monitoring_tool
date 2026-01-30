#!/usr/bin/env python3
"""
SentinelEdge Server - Main Entry Point (Phase-1 Redesigned)
Live telemetry ingestion matching API specification.
"""
import sys
import logging
import threading
import time
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).parent))

from server_app import create_app
from extensions import db
from server_config import get_config
from logging_config import setup_logging, AgentLogger
from flask import jsonify

logger = logging.getLogger(__name__)

def init_database(app):
    """Initialize database tables."""
    with app.app_context():
        try:
            db.create_all()
            logger.info("Database tables created/verified")
        except Exception as e:
            logger.error(f"Database init failed: {e}")
            raise

def apply_startup_fixes(app):
    """Run self-healing scripts on startup."""
    from scripts.fixes.ensure_procedures_correct import apply_fixes as fix_procedures
    # Import other fixes dynamically or path-based if needed, but procedures are critical
    
    with app.app_context():
        try:
            logger.info("[STARTUP] Running self-healing scripts...")
            
            # 1. Fix Stored Procedures (Round function error)
            fix_procedures()
            
            # 2. Add Indexes (Performance) - SKIPPED for clean startup
            # Use subprocess for scripts that are standalone
            # import subprocess
            # subprocess.run([sys.executable, 'scripts/fixes/add_indexes.py'], check=False)
            # logger.info("✓ Indexes verified")
            
            # 3. Apply Sync Functions - SKIPPED for clean startup
            # subprocess.run([sys.executable, 'scripts/fixes/apply_sync_functions.py'], check=False)
            # logger.info("✓ Sync functions verified")
            
            # 4. Fix Collation - SKIPPED for clean startup
            # subprocess.run([sys.executable, 'scripts/fixes/fix_collation.py'], check=False)

            logger.info("[STARTUP] Self-healing complete.")
        except Exception as e:
            logger.error(f"[STARTUP] Fix scripts failed (non-critical): {e}")


def sync_screen_time_background(app):
    """
    Background task: Sync ALL data every 5 minutes.
    - Syncs screen_time from telemetry
    - Syncs app_usage from app_sessions (source of truth)
    - Syncs domain_usage from domain_sessions (source of truth)
    """
    while True:
        try:
            time.sleep(60)  # Wait 1 minute (Optimized for shift)
            with app.app_context():
                from sqlalchemy import text
                
                # Sync screen_time
                result = db.session.execute(text(
                    "SELECT * FROM sync_screen_time_from_sessions(CURRENT_DATE)"
                ))
                rows = result.fetchall()
                
                # Sync app_usage from app_sessions
                db.session.execute(text(
                    "SELECT sync_app_usage_from_sessions(CURRENT_DATE)"
                ))
                
                # Sync domain_usage from domain_sessions
                db.session.execute(text(
                    "SELECT sync_domain_usage_from_sessions(CURRENT_DATE)"
                ))
                
                db.session.commit()
                logger.info(f"[SYNC] Data synced: {len(rows)} agents, app_usage + domain_usage updated")
        except Exception as e:
            logger.error(f"[SYNC] Error syncing data: {e}")


def cleanup_background(app):
    """
    FIX 3: Hourly cleanup - Purge old data + sync aggregates + classify domains.
    Runs every hour to clean up old raw events and sessions.
    """
    import server_models
    from datetime import datetime, timedelta, timezone
    
    while True:
        try:
            time.sleep(3600)  # 1 hour
            with app.app_context():
                from sqlalchemy import text
                
                # ================================================================
                # PART 1: PURGE OLD DATA
                # ================================================================
                # Purge old raw events (30 days retention)
                # Use timezone-aware UTC time
                cutoff_30d = datetime.now(timezone.utc) - timedelta(days=30)
                # Ensure we compare against offset-naive if DB is naive, or aware if aware.
                # Usually naive UTC is stored in Postgres TIMESTAMP WITHOUT TIME ZONE
                # So we might need to strip tzinfo if DB columns are naive. 
                # Ideally, we should migrate to TIMESTAMP WITH TIME ZONE, but for now:
                cutoff_30d = cutoff_30d.replace(tzinfo=None)

                purged_raw = db.session.query(server_models.RawEvent).filter(
                    server_models.RawEvent.received_at < cutoff_30d
                ).delete(synchronize_session='fetch')
                
                # Purge old app sessions (90 days retention)
                cutoff_90d = datetime.now(timezone.utc) - timedelta(days=90)
                cutoff_90d = cutoff_90d.replace(tzinfo=None) # Strip timezone for naive DB columns
                
                purged_sessions = 0
                if hasattr(server_models, 'AppSession'):
                    purged_sessions = db.session.query(server_models.AppSession).filter(
                        server_models.AppSession.created_at < cutoff_90d
                    ).delete(synchronize_session='fetch')
                
                db.session.commit()
                logger.info(f"[CLEANUP] Purged: raw_events={purged_raw}, sessions={purged_sessions}")
                
                # ================================================================
                # PART 2: CLASSIFY UNREVIEWED DOMAINS (AUTOMATIC!)
                # ================================================================
                try:
                    # Get unreviewed sessions
                    unreviewed = server_models.DomainSession.query.filter(
                        server_models.DomainSession.domain_source == 'agent',
                        server_models.DomainSession.needs_review == True,
                        server_models.DomainSession.raw_title.isnot(None)
                    ).limit(500).all()
                    
                    if unreviewed:
                        # Get classification rules
                        rules = db.session.execute(text('''
                            SELECT pattern, pattern_type, classified_as, action
                            FROM domain_classification_rules
                            WHERE is_active = TRUE
                            ORDER BY priority ASC
                        ''')).fetchall()
                        
                        classified = 0
                        for session in unreviewed:
                            raw_title = (session.raw_title or '').lower()
                            raw_url = (session.raw_url or '').lower()
                            
                            for rule in rules:
                                pattern, pattern_type, classified_as, action = rule
                                pattern_lower = pattern.lower()
                                
                                # Match pattern
                                if pattern_type == 'substring':
                                    match = pattern_lower in raw_title or pattern_lower in raw_url
                                elif pattern_type == 'exact':
                                    match = pattern_lower == raw_title or pattern_lower == raw_url
                                else:
                                    match = False
                                
                                if match:
                                    session.domain = 'ignored' if action == 'ignore' else classified_as
                                    session.domain_source = 'classifier'
                                    session.needs_review = False
                                    classified += 1
                                    break
                        
                        db.session.commit()
                        if classified > 0:
                            logger.info(f"[CLASSIFY] Auto-classified {classified}/{len(unreviewed)} domains")
                            
                except Exception as e:
                    logger.warning(f"[CLASSIFY] Error (non-critical): {e}")
                
        except Exception as e:
            logger.error(f"[CLEANUP] Error: {e}")



def create_application():
    """
    Application factory for production deployment.
    Returns configured Flask app for Gunicorn.
    
    Usage: gunicorn -c gunicorn_config.py server_main:application
    """
    config = get_config()
    setup_logging(log_level=config.LOG_LEVEL, log_dir='logs')
    
    logger.info("=" * 70)
    logger.info(" SentinelEdge Server v2.0.0 - Production Mode")
    logger.info("=" * 70)
    
    app = create_app()
    
    # Add health endpoint
    @app.route('/', methods=['GET'])
    def health():
        return jsonify({
            "status": "ok",
            "service": "SentinelEdge Server",
            "version": "2.0.0"
        }), 200
    
    init_database(app)
    apply_startup_fixes(app)
    
    # Start background sync thread
    sync_thread = threading.Thread(
        target=sync_screen_time_background,
        args=(app,),
        daemon=True,
        name='ScreenTimeSyncThread'
    )
    sync_thread.start()
    logger.info("Background sync thread started (runs every 1 minute)")
    
    # FIX 3: Start cleanup thread (hourly)
    cleanup_thread = threading.Thread(
        target=cleanup_background,
        args=(app,),
        daemon=True,
        name='CleanupThread'
    )
    cleanup_thread.start()
    logger.info("Cleanup thread started (runs hourly)")
    
    logger.info("Server initialized successfully!")
    logger.info("=" * 70)
    
    return app

# Create application instance for Gunicorn
# This is what gunicorn imports: server_main:application
application = None
try:
    application = create_application()
except Exception as e:
    # Don't fail on import if not in production context
    logging.warning(f"Application not created on import: {e}")


def main():
    """Main entry point for development server only."""
    global application
    
    print("=" * 70)
    print(" WARNING: Running development server!")
    print(" For production, use: gunicorn -c gunicorn_config.py server_main:application")
    print("=" * 70)
    print()
    
    # Create app if not already created
    if application is None:
        application = create_application()
    
    config = get_config()
    host = config.HOST
    port = config.PORT
    
    logger.info(f"Development server starting on http://{host}:{port}")
    logger.info(f"API Base: http://{host}:{port}/api/v1/")
    logger.info(f"Dashboard: http://{host}:{port}/dashboard/")
    logger.info(f"Health Check: http://{host}:{port}/")
    logger.info("Press Ctrl+C to stop")
    
    try:
        application.run(
            host=host,
            port=port,
            debug=False,
            threaded=True,
            use_reloader=False
        )
    except KeyboardInterrupt:
        logger.info("\nShutting down...")
        logger.info("Server stopped by user")
        sys.exit(0)
    except Exception as e:
        logger.critical(f"Server error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()

