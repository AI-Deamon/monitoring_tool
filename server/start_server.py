#!/usr/bin/env python3
"""
SentinelEdge Server - Smart Startup
====================================
Automatically runs all necessary setup scripts and starts the server.
Just run: python start_server.py
"""
import sys
import os
from pathlib import Path
from sqlalchemy import text
import logging

# Setup path
sys.path.insert(0, str(Path(__file__).parent))

from server_app import create_app
from extensions import db

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)
logger = logging.getLogger(__name__)

def print_banner():
    """Print startup banner"""
    print("""
╔══════════════════════════════════════════════════════════╗
║         SentinelEdge Server - Smart Startup              ║
║         Automatic Setup & Configuration                  ║
╚══════════════════════════════════════════════════════════╝
""")

def check_database_connection(app):
    """Check if database is accessible"""
    logger.info("[1/6] Checking database connection...")
    with app.app_context():
        try:
            db.session.execute(text("SELECT 1"))
            logger.info("  ✅ Database connected")
            return True
        except Exception as e:
            logger.error(f"  ❌ Database connection failed: {e}")
            logger.error("\n  Please check:")
            logger.error("  1. PostgreSQL is running")
            logger.error("  2. DATABASE_URL in .env is correct")
            logger.error("  3. Database exists (createdb sentineledge)")
            return False

def create_tables(app):
    """Create all database tables"""
    logger.info("[2/6] Creating/verifying database tables...")
    with app.app_context():
        try:
            db.create_all()
            logger.info("  ✅ All tables created/verified")
            return True
        except Exception as e:
            logger.error(f"  ❌ Table creation failed: {e}")
            return False

def install_stored_procedures(app):
    """Install all critical stored procedures using raw connection"""
    logger.info("[3/6] Installing stored procedures...")
    with app.app_context():
        try:
            connection = db.engine.raw_connection()
            cursor = connection.cursor()
            
            # 1. Drop old functions to avoid return type conflicts
            logger.info("  - Dropping legacy functions...")
            cursor.execute("DROP FUNCTION IF EXISTS process_screentime_event(VARCHAR, TIMESTAMP, INTEGER, INTEGER, INTEGER, VARCHAR) CASCADE;")
            cursor.execute("DROP FUNCTION IF EXISTS process_app_switch_event(VARCHAR, VARCHAR, VARCHAR, VARCHAR, VARCHAR, VARCHAR, TIMESTAMP, TIMESTAMP, INTEGER, VARCHAR) CASCADE;")
            cursor.execute("DROP FUNCTION IF EXISTS process_domain_switch_event(VARCHAR, VARCHAR, VARCHAR, TEXT, TEXT, VARCHAR, TIMESTAMP, TIMESTAMP, INTEGER, VARCHAR) CASCADE;")
            
            # 2. Process screentime event
            logger.info("  - Creating process_screentime_event...")
            cursor.execute("""
                CREATE OR REPLACE FUNCTION process_screentime_event(
                    p_agent_id VARCHAR, p_timestamp TIMESTAMP,
                    p_active_total INTEGER, p_idle_total INTEGER,
                    p_locked_total INTEGER, p_state VARCHAR
                ) RETURNS TABLE(status text, message text) AS $$
                DECLARE v_date DATE;
                BEGIN
                    v_date := p_timestamp::DATE;
                    INSERT INTO screen_time (agent_id, date, active_seconds, idle_seconds, locked_seconds, last_updated)
                    VALUES (p_agent_id::UUID, v_date, p_active_total, p_idle_total, p_locked_total, NOW())
                    ON CONFLICT (agent_id, date) DO UPDATE SET
                        active_seconds = GREATEST(screen_time.active_seconds, EXCLUDED.active_seconds),
                        idle_seconds = GREATEST(screen_time.idle_seconds, EXCLUDED.idle_seconds),
                        locked_seconds = GREATEST(screen_time.locked_seconds, EXCLUDED.locked_seconds),
                        last_updated = NOW();
                    RETURN QUERY SELECT 'success'::text, 'Screentime processed'::text;
                EXCEPTION WHEN OTHERS THEN
                    RETURN QUERY SELECT 'error'::text, SQLERRM::text;
                END;
                $$ LANGUAGE plpgsql;
            """)
            
            # 3. Process app switch event  
            logger.info("  - Creating process_app_switch_event...")
            cursor.execute("""
                CREATE OR REPLACE FUNCTION process_app_switch_event(
                    p_agent_id VARCHAR, p_username VARCHAR, p_app VARCHAR,
                    p_friendly_name VARCHAR, p_category VARCHAR, p_window_title VARCHAR,
                    p_session_start TIMESTAMP, p_session_end TIMESTAMP,
                    p_total_seconds INTEGER, p_idempotency_key VARCHAR
                ) RETURNS TABLE(status text, message text) AS $$
                DECLARE v_date DATE;
                BEGIN
                    v_date := p_session_start::DATE;
                    IF p_app IS NULL OR p_app = '' THEN
                        RETURN QUERY SELECT 'skipped'::TEXT, 'NULL app'::TEXT;
                        RETURN;
                    END IF;
                    IF p_total_seconds < 0 OR p_total_seconds > 28800 THEN
                        RETURN QUERY SELECT 'skipped'::TEXT, 'Invalid duration'::TEXT;
                        RETURN;
                    END IF;
                    BEGIN
                        INSERT INTO app_sessions (agent_id, app, window_title, start_time, end_time, duration_seconds, created_at)
                        VALUES (p_agent_id::UUID, p_app, p_window_title, p_session_start, p_session_end, p_total_seconds, NOW());
                    EXCEPTION WHEN unique_violation THEN
                        RETURN QUERY SELECT 'skipped'::text, 'Duplicate'::text;
                        RETURN;
                    END;
                    INSERT INTO app_usage (agent_id, date, app, duration_seconds, session_count, last_updated)
                    VALUES (p_agent_id::UUID, v_date, p_app, p_total_seconds, 1, NOW())
                    ON CONFLICT (agent_id, date, app) DO UPDATE SET
                        duration_seconds = app_usage.duration_seconds + EXCLUDED.duration_seconds,
                        session_count = app_usage.session_count + 1,
                        last_updated = NOW();
                    RETURN QUERY SELECT 'success'::text, 'Processed'::text;
                EXCEPTION WHEN OTHERS THEN
                    RETURN QUERY SELECT 'error'::text, SQLERRM::text;
                END;
                $$ LANGUAGE plpgsql;
            """)
            
            # 4. Process domain switch event
            logger.info("  - Creating process_domain_switch_event...")
            cursor.execute("""
                CREATE OR REPLACE FUNCTION process_domain_switch_event(
                    p_agent_id VARCHAR, p_username VARCHAR, p_domain VARCHAR,
                    p_raw_title TEXT, p_raw_url TEXT, p_browser VARCHAR,
                    p_session_start TIMESTAMP, p_session_end TIMESTAMP,
                    p_duration_seconds INTEGER, p_idempotency_key VARCHAR
                ) RETURNS TABLE(status text, message text) AS $$
                DECLARE v_date DATE;
                BEGIN
                    v_date := p_session_start::DATE;
                    INSERT INTO domain_sessions (agent_id, domain, raw_title, raw_url, browser,
                        start_time, end_time, duration_seconds, domain_source, needs_review, idempotency_key)
                    VALUES (p_agent_id::UUID, p_domain, p_raw_title, p_raw_url, p_browser,
                        p_session_start, p_session_end, p_duration_seconds, 'agent', FALSE, p_idempotency_key);
                    INSERT INTO domain_usage (agent_id, date, domain, duration_seconds, session_count, last_updated)
                    VALUES (p_agent_id::UUID, v_date, p_domain, p_duration_seconds, 1, NOW())
                    ON CONFLICT (agent_id, date, domain) DO UPDATE SET
                        duration_seconds = domain_usage.duration_seconds + EXCLUDED.duration_seconds,
                        session_count = domain_usage.session_count + 1,
                        last_updated = NOW();
                    RETURN QUERY SELECT 'success'::text, 'Processed'::text;
                EXCEPTION WHEN OTHERS THEN
                    RETURN QUERY SELECT 'error'::text, SQLERRM::text;
                END;
                $$ LANGUAGE plpgsql;
            """)
            
            connection.commit()
            cursor.close()
            connection.close()
            logger.info("  ✅ Stored procedures installed")
            return True
        except Exception as e:
            logger.error(f"  ❌ Procedure installation failed: {e}")
            return False

def fix_schema(app):
    """Fix schema issues (add missing columns)"""
    logger.info("[4/6] Fixing schema (adding missing columns)...")
    with app.app_context():
        try:
            # Add idempotency_key to domain_sessions if missing
            db.session.execute(text("""
                ALTER TABLE domain_sessions 
                ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(255);
            """))
            db.session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_domain_sessions_idempotency_key 
                ON domain_sessions(idempotency_key);
            """))
            db.session.commit()
            logger.info("  ✅ Schema fixed")
            return True
        except Exception as e:
            logger.error(f"  ❌ Schema fix failed: {e}")
            db.session.rollback()
            return False

def create_default_admin(app):
    """Create default admin user if not exists"""
    logger.info("[5/6] Checking admin user...")
    with app.app_context():
        try:
            from auth import DashboardUser
            admin = DashboardUser.query.filter_by(username='admin').first()
            if not admin:
                admin = DashboardUser(username='admin', role='admin')
                admin.set_password('changeme123')
                db.session.add(admin)
                db.session.commit()
                logger.info("  ✅ Default admin created (admin/changeme123)")
                logger.warning("  ⚠️  CHANGE PASSWORD IMMEDIATELY!")
            else:
                logger.info("  ✅ Admin user exists")
            return True
        except Exception as e:
            logger.error(f"  ❌ Admin creation failed: {e}")
            db.session.rollback()
            return False

def start_server(app):
    """Start the Flask server"""
    logger.info("[6/6] Starting server...")
    logger.info("\n" + "="*60)
    logger.info("✅ AUTO-SETUP COMPLETE!")
    logger.info("="*60)
    logger.info("\n🚀 Server starting...")
    logger.info("   Dashboard: http://localhost:5000/dashboard")
    logger.info("   Login: admin / changeme123")
    logger.info("\n⚠️  Press Ctrl+C to stop\n")
    
    # Import and run the actual server
    from server_main import main
    main()

def main():
    """Main startup workflow"""
    print_banner()
    
    # Check for --no-start flag
    skip_start = "--no-start" in sys.argv
    
    # Create app
    app = create_app()
    
    # Run all setup steps
    steps = [
        (check_database_connection, app),
        (create_tables, app),
        (install_stored_procedures, app),
        (fix_schema, app),
        (create_default_admin, app),
    ]
    
    for step_func, *args in steps:
        if not step_func(*args):
            logger.error("\n❌ Setup failed. Please fix errors and try again.")
            sys.exit(1)
    
    # Start server if not skipped
    if not skip_start:
        start_server(app)
    else:
        logger.info("\n✅ Setup complete! (Skipping server start as requested)\n")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Server stopped by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"\n❌ Fatal error: {e}")
        sys.exit(1)

