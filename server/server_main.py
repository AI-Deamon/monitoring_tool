#!/usr/bin/env python3
"""
SentinelEdge Server - Main Entry Point (Phase-1 Redesigned)
Live telemetry ingestion matching API specification.
"""
import sys
import os
import json
import logging
import threading
import time
from pathlib import Path
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, str(Path(__file__).parent))

from server_app import create_app
from extensions import db
from server_config import get_config
from logging_config import setup_logging, AgentLogger
from flask import jsonify

logger = logging.getLogger(__name__)


def _get_server_app_version() -> str:
    """Resolve server app version for logs and health endpoint."""
    env_version = os.getenv("SERVER_APP_VERSION", "").strip()
    if env_version:
        return env_version

    latest_file = Path(__file__).resolve().parent / "updates" / "latest.json"
    try:
        if latest_file.exists():
            data = json.loads(latest_file.read_text(encoding="utf-8"))
            version = str(data.get("version", "")).strip()
            if version:
                return version
    except Exception:
        pass

    return "unknown"

def init_database(app):
    """Note: Tables are now managed exclusively via Alembic migrations."""
    logger.info("Database schema is managed via Alembic migrations.")
    # db.create_all() removed to enforce Alembic-only schema management.

def apply_startup_fixes(app):
    """Run optional self-healing scripts on startup.

    Stored procedures are owned by the Alembic migration chain; the
    scripts.fixes package is a legacy add-on that is not part of the repo,
    so its absence must never prevent the server from booting.
    """
    try:
        from scripts.fixes.ensure_procedures_correct import apply_fixes as fix_procedures
    except ImportError:
        logger.info("[STARTUP] scripts.fixes not present - skipping self-healing "
                    "(schema/procedures are managed by Alembic)")
        return

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
    - Syncs screen_time from spans for the fully-elapsed day (reconcile-and-set)
    - Syncs app_usage from app_sessions (source of truth)
    - Syncs domain_usage from domain_sessions (source of truth)

    Spans are the sanctioned elapsed-day writer (FR-006): for the last fully
    elapsed UTC day, sync_screen_time_from_spans overwrites the row from the
    full span sum. The cumulative counter in process_screentime_event remains
    the in-progress-day live estimate only. The dedicated daily job
    (reconcile_elapsed_screentime_days) covers the full 7-day window for late
    spans.
    """
    from leader_election import get_leader
    leader = get_leader(app)
    while True:
        try:
            time.sleep(60)  # Wait 1 minute (Optimized for shift)
            if not leader.check():
                continue
            with app.app_context():
                from sqlalchemy import text

                # screen_time for the fully-elapsed day comes from spans, not
                # from a cumulative merge: sync_screen_time_from_spans is the
                # sanctioned elapsed-day writer (reconcile-and-set, idempotent,
                # corrects downward). The per-event cumulative writer
                # (process_screentime_event) only estimates the in-progress
                # day. This job used to call sync_screen_time_from_sessions(),
                # which recomputed active_seconds from app_sessions and merged
                # it in via GREATEST(), a one-way ratchet that could never
                # correct itself downward. Removed; see plan doc.

                # Pass an explicit UTC date rather than relying on
                # Postgres's CURRENT_DATE, which resolves to this
                # connection's configured session timezone (IST on this
                # database) - the stored procedures filter sessions with
                # start_time::DATE = p_date, and start_time is always
                # stored as naive UTC, so an IST-valued p_date silently
                # mis-buckets sessions in the ~5.5h window after IST
                # midnight. This must match the daily job in
                # background_tasks.py::sync_yesterday_data(), which
                # already computes UTC explicitly.
                today_utc = datetime.now(timezone.utc).date()

                # Sync app_usage from app_sessions
                db.session.execute(
                    text("SELECT sync_app_usage_from_sessions(:d)"),
                    {"d": today_utc},
                )

                # Sync domain_usage from domain_sessions
                db.session.execute(
                    text("SELECT sync_domain_usage_from_sessions(:d)"),
                    {"d": today_utc},
                )

                # Reconcile the last fully-elapsed UTC day from spans
                # (authoritative; see docstring).
                db.session.execute(
                    text("SELECT sync_screen_time_from_spans(:d)"),
                    {"d": today_utc - timedelta(days=1)},
                )

                db.session.commit()
                logger.info("[SYNC] Data synced: app_usage + domain_usage + screen_time-from-spans updated")
        except Exception as e:
            logger.error(f"[SYNC] Error syncing data: {e}")


def cleanup_background(app):
    """
    FIX 3: Hourly domain auto-classification.
    Data-retention purging is owned by background_tasks.py's scheduled job.
    """
    import server_models
    from leader_election import get_leader
    leader = get_leader(app)

    while True:
        try:
            time.sleep(3600)  # 1 hour
            if not leader.check():
                continue
            with app.app_context():
                from sqlalchemy import text

                # NOTE: Data-retention purging (raw_events, app_sessions, domain
                # sessions/visits, state_changes) is no longer done here. It is
                # owned exclusively by background_tasks.py's scheduled
                # cleanup_old_data() job (which calls server_cleanup.cleanup_old_data()),
                # started from create_app(). Having two independent threads purge
                # the same tables on different schedules/cutoff columns was itself
                # a source of confusion and risk; this thread now only handles
                # domain auto-classification below.

                # ================================================================
                # CLASSIFY UNREVIEWED DOMAINS (AUTOMATIC!)
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
    server_version = _get_server_app_version()
    
    logger.info("=" * 70)
    logger.info(f" SentinelEdge Server v{server_version} - Production Mode")
    logger.info("=" * 70)
    
    app = create_app()
    
    # Add health endpoint
    @app.route('/', methods=['GET'])
    def health():
        return jsonify({
            "status": "ok",
            "service": "SentinelEdge Server",
            "version": server_version
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
        ssl_context = None
        if config.USE_TLS:
            import ssl
            ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            ssl_context.load_cert_chain(config.SSL_CERT_PATH, config.SSL_KEY_PATH)
            ssl_context.load_verify_locations(config.SSL_CA_PATH)
            ssl_context.verify_mode = ssl.CERT_REQUIRED
            logger.info(f"mTLS enabled for development server")

        application.run(
            host=host,
            port=port,
            debug=False,
            threaded=True,
            use_reloader=False,
            ssl_context=ssl_context
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

