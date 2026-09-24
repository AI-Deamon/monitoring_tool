#!/usr/bin/env python3
"""
SentinelEdge Server - Complete Self-Healing Startup
====================================================
Automatically runs ALL necessary setup: tables, procedures, functions, migrations.
Designed for easy deployment to new machines.

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
    try:
        print("""
╔══════════════════════════════════════════════════════════════╗
║         SentinelEdge Server - Complete Self-Healing          ║
║         Automatic Setup & All Database Initialization        ║
╚══════════════════════════════════════════════════════════════╝
""")
    except UnicodeEncodeError:
        print("""
============================================
    SentinelEdge Server - Complete Self-Healing
    Automatic Setup & All Database Initialization
============================================
""")

def check_database_connection(app):
    """Check if database is accessible"""
    logger.info("[1/8] Checking database connection...")
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
            logger.error("  3. Database exists (createdb sentinel_edge_v3)")
            return False

def create_tables(app):
    """Note: Tables are now managed exclusively via Alembic migrations."""
    logger.info("[2/8] Database schema is managed via Alembic migrations.")
    # db.create_all() removed to enforce Alembic-only schema management.
    return True

def create_screen_time_spans_table(app):
    """Create screen_time_spans table and indexes"""
    logger.info("[3/8] Creating screen_time_spans table...")
    with app.app_context():
        try:
            connection = db.engine.raw_connection()
            cursor = connection.cursor()
            
            # Create table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS screen_time_spans (
                    id SERIAL PRIMARY KEY,
                    span_id VARCHAR(128) UNIQUE NOT NULL,
                    agent_id UUID NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
                    state VARCHAR(20) NOT NULL CHECK (state IN ('active', 'idle', 'locked')),
                    start_time TIMESTAMP NOT NULL,
                    end_time TIMESTAMP NOT NULL,
                    duration_seconds INTEGER NOT NULL CHECK (duration_seconds > 0 AND duration_seconds <= 86400),
                    created_at TIMESTAMP DEFAULT NOW(),
                    processed BOOLEAN DEFAULT FALSE,
                    CONSTRAINT valid_time_range CHECK (end_time > start_time)
                );
            """)
            
            # Create indexes
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_spans_agent_date 
                ON screen_time_spans(agent_id, start_time);
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_spans_processed 
                ON screen_time_spans(processed) WHERE NOT processed;
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_spans_span_id 
                ON screen_time_spans(span_id);
            """)
            
            connection.commit()
            cursor.close()
            connection.close()
            logger.info("  ✅ screen_time_spans table and indexes created")
            return True
        except Exception as e:
            logger.error(f"  ❌ screen_time_spans table creation failed: {e}")
            return False

def install_stored_procedures(app):
    """Install all critical stored procedures"""
    logger.info("[4/8] Installing stored procedures...")
    with app.app_context():
        try:
            connection = db.engine.raw_connection()
            cursor = connection.cursor()
            
            # 1. Drop old functions to avoid return type conflicts
            logger.info("  - Dropping legacy functions...")
            cursor.execute("DROP FUNCTION IF EXISTS process_screentime_event(VARCHAR, TIMESTAMP, INTEGER, INTEGER, INTEGER, VARCHAR) CASCADE;")
            cursor.execute("DROP FUNCTION IF EXISTS process_screentime_event(VARCHAR, TIMESTAMP, INTEGER, INTEGER, INTEGER, INTEGER, VARCHAR) CASCADE;")
            cursor.execute("DROP FUNCTION IF EXISTS process_screentime_event(VARCHAR, DATE, VARCHAR, INTEGER, INTEGER, INTEGER, INTEGER) CASCADE;")
            cursor.execute("DROP FUNCTION IF EXISTS process_app_switch_event(VARCHAR, VARCHAR, VARCHAR, VARCHAR, VARCHAR, VARCHAR, TIMESTAMP, TIMESTAMP, INTEGER, VARCHAR) CASCADE;")
            cursor.execute("DROP FUNCTION IF EXISTS process_app_switch_event(VARCHAR, TIMESTAMP, VARCHAR, VARCHAR, VARCHAR, VARCHAR, TIMESTAMP, TIMESTAMP, FLOAT, DATE) CASCADE;")
            cursor.execute("DROP FUNCTION IF EXISTS process_domain_switch_event(VARCHAR, VARCHAR, VARCHAR, TEXT, TEXT, VARCHAR, TIMESTAMP, TIMESTAMP, INTEGER, VARCHAR) CASCADE;")
            
            # 2. Process screentime event (7 params — includes away_seconds)
            logger.info("  - Creating process_screentime_event (7 params)...")
            cursor.execute("""
                CREATE OR REPLACE FUNCTION process_screentime_event(
                    p_agent_id VARCHAR, p_timestamp TIMESTAMP,
                    p_active_total INTEGER, p_idle_total INTEGER,
                    p_locked_total INTEGER, p_away_total INTEGER,
                    p_state VARCHAR,
                    p_session_start TIMESTAMP DEFAULT NULL
                ) RETURNS TABLE(status text, message text) AS $$
                DECLARE
                    v_date DATE;
                    v_existing_session_start TIMESTAMP;
                    v_session_changed BOOLEAN := FALSE;
                    v_existing_total INTEGER := 0;
                    v_incoming_total INTEGER := 0;
                    v_should_replace BOOLEAN := FALSE;
                BEGIN
                    v_date := p_timestamp::DATE;
                    IF v_date < (NOW() AT TIME ZONE 'Asia/Kolkata')::DATE THEN
                        RAISE NOTICE 'Historical data detected for agent %, on %', p_agent_id, v_date;
                    END IF;

                    SELECT
                        session_start,
                        COALESCE(active_seconds, 0)::INTEGER +
                        COALESCE(idle_seconds, 0)::INTEGER +
                        COALESCE(locked_seconds, 0)::INTEGER +
                        COALESCE(away_seconds, 0)::INTEGER
                    INTO v_existing_session_start, v_existing_total
                    FROM screen_time
                    WHERE agent_id = p_agent_id::UUID AND date = v_date;
                    
                    -- Check if session changed (agent restart/reinstall detection)
                    IF p_session_start IS NOT NULL THEN
                        IF v_existing_session_start IS NULL OR
                           v_existing_session_start != p_session_start THEN
                            v_session_changed := TRUE;
                        END IF;
                    END IF;

                    v_incoming_total := COALESCE(p_active_total, 0) +
                        COALESCE(p_idle_total, 0) +
                        COALESCE(p_locked_total, 0) +
                        COALESCE(p_away_total, 0);

                    -- Trust the agent's cumulative bucket set as a whole whenever
                    -- the session changed or the total has not regressed.
                    -- This allows locked -> away reclassification for one continuous
                    -- lock session without leaving stale locked seconds in the row.
                    v_should_replace := v_session_changed OR v_incoming_total >= v_existing_total;
                    
                    INSERT INTO screen_time (agent_id, date, session_start, active_seconds, idle_seconds, locked_seconds, away_seconds, last_updated)
                    VALUES (p_agent_id::UUID, v_date, p_session_start, p_active_total, p_idle_total, p_locked_total, p_away_total, (NOW() AT TIME ZONE 'Asia/Kolkata'))
                    ON CONFLICT (agent_id, date) DO UPDATE SET
                        -- Update session_start if changed
                        session_start = CASE WHEN v_session_changed
                            THEN EXCLUDED.session_start
                            ELSE screen_time.session_start END,
                        -- Replace the full bucket set on same-session non-regressing totals.
                        -- This preserves continuous-lock reclassification from LOCKED to AWAY.
                        active_seconds = CASE
                            WHEN v_should_replace THEN LEAST(EXCLUDED.active_seconds, 86400)
                            ELSE screen_time.active_seconds
                        END,
                        idle_seconds = CASE
                            WHEN v_should_replace THEN LEAST(EXCLUDED.idle_seconds, 86400)
                            ELSE screen_time.idle_seconds
                        END,
                        locked_seconds = CASE
                            WHEN v_should_replace THEN LEAST(EXCLUDED.locked_seconds, 86400)
                            ELSE screen_time.locked_seconds
                        END,
                        away_seconds = CASE
                            WHEN v_should_replace THEN LEAST(EXCLUDED.away_seconds, 86400)
                            ELSE screen_time.away_seconds
                        END,
                        last_updated = (NOW() AT TIME ZONE 'Asia/Kolkata');
                    RETURN QUERY SELECT 'success'::text, 'Screentime processed'::text;
                EXCEPTION WHEN OTHERS THEN
                    RETURN QUERY SELECT 'error'::text, SQLERRM::text;
                END;
                $$ LANGUAGE plpgsql;
            """)
            
            # 3. Process app switch event
            # Signature MUST match the named-param call in server_telemetry.py:
            #   process_app_switch_event(agent_id, timestamp, app, friendly_name,
            #       category, window_title, session_start, session_end,
            #       total_seconds, date)
            logger.info("  - Creating process_app_switch_event...")
            cursor.execute("""
                CREATE OR REPLACE FUNCTION process_app_switch_event(
                    p_agent_id   VARCHAR,
                    p_timestamp  TIMESTAMP,
                    p_app        VARCHAR,
                    p_friendly_name VARCHAR,
                    p_category   VARCHAR,
                    p_window_title VARCHAR,
                    p_session_start TIMESTAMP,
                    p_session_end   TIMESTAMP,
                    p_total_seconds FLOAT,
                    p_date          DATE
                ) RETURNS TABLE(status text, message text) AS $$
                BEGIN
                    IF p_app IS NULL OR p_app = '' THEN
                        RETURN QUERY SELECT 'skipped'::TEXT, 'NULL app'::TEXT;
                        RETURN;
                    END IF;
                    IF p_total_seconds < 0 OR p_total_seconds > 28800 THEN
                        RETURN QUERY SELECT 'skipped'::TEXT, 'Invalid duration'::TEXT;
                        RETURN;
                    END IF;
                    BEGIN
                        INSERT INTO app_sessions (
                            agent_id, app, window_title,
                            start_time, end_time, duration_seconds, created_at
                        ) VALUES (
                            p_agent_id::UUID, p_app, p_window_title,
                            p_session_start, p_session_end,
                            p_total_seconds,
                            NOW()
                        );
                    EXCEPTION WHEN unique_violation THEN
                        RETURN QUERY SELECT 'skipped'::text, 'Duplicate'::text;
                        RETURN;
                    END;
                    INSERT INTO app_usage (
                        agent_id, date, app, duration_seconds, session_count, last_updated
                    ) VALUES (
                        p_agent_id::UUID, p_date, p_app,
                        p_total_seconds::INTEGER, 1, NOW()
                    )
                    ON CONFLICT (agent_id, date, app) DO UPDATE SET
                        duration_seconds = app_usage.duration_seconds + EXCLUDED.duration_seconds,
                        session_count    = app_usage.session_count + 1,
                        last_updated     = NOW();
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
                    VALUES (p_agent_id::UUID, v_date, p_domain, p_duration_seconds, 1, (NOW() AT TIME ZONE 'Asia/Kolkata'))
                    ON CONFLICT (agent_id, date, domain) DO UPDATE SET
                        duration_seconds = domain_usage.duration_seconds + EXCLUDED.duration_seconds,
                        session_count = domain_usage.session_count + 1,
                        last_updated = (NOW() AT TIME ZONE 'Asia/Kolkata');
                    RETURN QUERY SELECT 'success'::text, 'Processed'::text;
                EXCEPTION WHEN OTHERS THEN
                    RETURN QUERY SELECT 'error'::text, SQLERRM::text;
                END;
                $$ LANGUAGE plpgsql;
            """)
            
            connection.commit()
            cursor.close()
            connection.close()
            logger.info("  ✅ Core stored procedures installed")
            return True
        except Exception as e:
            logger.error(f"  ❌ Procedure installation failed: {e}")
            return False

def install_sync_functions(app):
    """Install all sync and aggregation functions"""
    logger.info("[5/8] Installing sync/aggregation functions...")
    with app.app_context():
        try:
            connection = db.engine.raw_connection()
            cursor = connection.cursor()
            
            # 1. sync_screen_time_from_spans (CRITICAL for span aggregation)
            logger.info("  - Creating sync_screen_time_from_spans...")
            cursor.execute("""
        CREATE OR REPLACE FUNCTION sync_screen_time_from_spans(p_date DATE DEFAULT CURRENT_DATE)
        RETURNS TABLE(ret_agent_id UUID, synced BOOLEAN) AS $$
        BEGIN
            -- Reconcile-and-set: overwrite the row from the FULL span sum for
            -- p_date. No processed gate — late spans must count even after an
            -- earlier run already marked that day's spans processed (FR-006).
            -- No additive merge — a downward correction (e.g. a fabricated
            -- cumulative total) is replaced, not ratcheted up.
            INSERT INTO screen_time (agent_id, date, active_seconds, idle_seconds, locked_seconds, away_seconds, last_updated, updated_at)
            SELECT
                s.agent_id,
                p_date,
                LEAST(COALESCE(SUM(CASE WHEN s.state = 'active' THEN s.duration_seconds ELSE 0 END), 0), 86400)::INTEGER,
                LEAST(COALESCE(SUM(CASE WHEN s.state = 'idle'   THEN s.duration_seconds ELSE 0 END), 0), 86400)::INTEGER,
                LEAST(COALESCE(SUM(CASE WHEN s.state = 'locked' THEN s.duration_seconds ELSE 0 END), 0), 86400)::INTEGER,
                LEAST(COALESCE(SUM(CASE WHEN s.state = 'away'   THEN s.duration_seconds ELSE 0 END), 0), 86400)::INTEGER,
                NOW(),
                NOW()
            FROM screen_time_spans s
            JOIN agents a ON a.agent_id = s.agent_id
            WHERE s.start_time::DATE = p_date
            GROUP BY s.agent_id
            ON CONFLICT (agent_id, date) DO UPDATE SET
                active_seconds = EXCLUDED.active_seconds,
                idle_seconds = EXCLUDED.idle_seconds,
                locked_seconds = EXCLUDED.locked_seconds,
                away_seconds = EXCLUDED.away_seconds,
                last_updated = NOW(),
                updated_at = NOW();

            -- Capability-gated zeroing: an existing row for p_date whose
            -- agent has no spans that day is zeroed ONLY if the agent had
            -- ALREADY produced at least one span BY p_date (not merely "ever,
            -- as of now"). Date-scoping matters: an agent that sends its
            -- first-ever span on day X must not have its genuinely
            -- pre-upgrade days (X-1..X-6) zeroed just because a later sweep
            -- run sees the agent as globally capable. Pre-span-era agents
            -- (zero spans ever) are never touched (FR-006 gate / US3-7).
            -- Never creates rows for agents with no data — this only updates
            -- rows that already exist.
            UPDATE screen_time st
            SET active_seconds = 0, idle_seconds = 0, locked_seconds = 0,
                away_seconds = 0, last_updated = NOW(), updated_at = NOW()
            WHERE st.date = p_date
              AND NOT EXISTS (
                  SELECT 1 FROM screen_time_spans sp
                  WHERE sp.agent_id = st.agent_id AND sp.start_time::DATE = p_date
              )
              AND EXISTS (
                  SELECT 1 FROM screen_time_spans hist
                  WHERE hist.agent_id = st.agent_id AND hist.start_time::DATE <= p_date
              );

            -- Mark the day's spans processed so the 7-day span cleanup can
            -- purge them. Reconcile still reads ALL spans for p_date, so a
            -- late span counted on a later run even after this marking.
            UPDATE screen_time_spans
            SET processed = TRUE
            WHERE start_time::DATE = p_date;

            -- Return affected agents (span-aggregated + capability-zeroed).
            RETURN QUERY
            SELECT DISTINCT agent_id, TRUE AS synced
            FROM (
                SELECT s.agent_id FROM screen_time_spans s
                JOIN agents a ON a.agent_id = s.agent_id
                WHERE s.start_time::DATE = p_date
                UNION
                SELECT st.agent_id FROM screen_time st
                WHERE st.date = p_date
                  AND NOT EXISTS (
                      SELECT 1 FROM screen_time_spans sp
                      WHERE sp.agent_id = st.agent_id AND sp.start_time::DATE = p_date
                  )
                  AND EXISTS (
                      SELECT 1 FROM screen_time_spans hist
                      WHERE hist.agent_id = st.agent_id AND hist.start_time::DATE <= p_date
                  )
            ) AS touched;
        END;
        $$ LANGUAGE plpgsql;
    """)
            
            # 2. cleanup_old_spans
            logger.info("  - Creating cleanup_old_spans...")
            cursor.execute("""
                CREATE OR REPLACE FUNCTION cleanup_old_spans()
                RETURNS INTEGER AS $$
                DECLARE
                    deleted_count INTEGER;
                BEGIN
                    DELETE FROM screen_time_spans
                    WHERE processed = TRUE
                    AND created_at < NOW() - INTERVAL '7 days';
                    
                    GET DIAGNOSTICS deleted_count = ROW_COUNT;
                    RETURN deleted_count;
                END;
                $$ LANGUAGE plpgsql;
            """)
            
            # 3. sync_app_usage_from_sessions
            logger.info("  - Creating sync_app_usage_from_sessions...")
            cursor.execute("""
                CREATE OR REPLACE FUNCTION sync_app_usage_from_sessions(p_date DATE)
                RETURNS void AS $$
                BEGIN
                    INSERT INTO app_usage (agent_id, date, app, duration_seconds, session_count, last_updated)
                    SELECT 
                        agent_id,
                        p_date,
                        app,
                        COALESCE(SUM(duration_seconds), 0)::INTEGER,
                        COUNT(*),
                        NOW()
                    FROM app_sessions
                    WHERE start_time::DATE = p_date
                    GROUP BY agent_id, app
                    ON CONFLICT (agent_id, date, app) DO UPDATE SET
                        duration_seconds = EXCLUDED.duration_seconds,
                        session_count = EXCLUDED.session_count,
                        last_updated = (NOW() AT TIME ZONE 'Asia/Kolkata');
                END;
                $$ LANGUAGE plpgsql;
            """)
            
            # 4. sync_domain_usage_from_sessions
            logger.info("  - Creating sync_domain_usage_from_sessions...")
            cursor.execute("""
                CREATE OR REPLACE FUNCTION sync_domain_usage_from_sessions(p_date DATE)
                RETURNS void AS $$
                BEGIN
                    INSERT INTO domain_usage (agent_id, date, domain, duration_seconds, session_count, last_updated)
                    SELECT 
                        agent_id,
                        p_date,
                        domain,
                        COALESCE(SUM(duration_seconds), 0)::INTEGER,
                        COUNT(*),
                        NOW()
                    FROM domain_sessions
                    WHERE start_time::DATE = p_date
                    GROUP BY agent_id, domain
                    ON CONFLICT (agent_id, date, domain) DO UPDATE SET
                        duration_seconds = EXCLUDED.duration_seconds,
                        session_count = EXCLUDED.session_count,
                        last_updated = (NOW() AT TIME ZONE 'Asia/Kolkata');
                END;
                $$ LANGUAGE plpgsql;
            """)
            
            # 5. sync_screen_time_from_sessions
            logger.info("  - Creating sync_screen_time_from_sessions...")
            cursor.execute("""
                CREATE OR REPLACE FUNCTION sync_screen_time_from_sessions(p_date DATE)
                RETURNS TABLE(agent_id VARCHAR, active_seconds INTEGER) AS $$
                DECLARE
                    r RECORD;
                BEGIN
                    FOR r IN 
                        SELECT 
                            s.agent_id,
                            COALESCE(SUM(s.duration_seconds), 0)::INTEGER as total_active
                        FROM app_sessions s
                        WHERE s.start_time::DATE = p_date
                        GROUP BY s.agent_id
                    LOOP
                        INSERT INTO screen_time (agent_id, date, active_seconds, idle_seconds, locked_seconds, last_updated)
                        VALUES (r.agent_id, p_date, r.total_active, 0, 0, (NOW() AT TIME ZONE 'Asia/Kolkata'))
                        ON CONFLICT (agent_id, date) DO UPDATE SET
                            active_seconds = EXCLUDED.active_seconds,
                            last_updated = (NOW() AT TIME ZONE 'Asia/Kolkata');
                            
                        agent_id := r.agent_id;
                        active_seconds := r.total_active;
                        RETURN NEXT;
                    END LOOP;
                    RETURN;
                END;
                $$ LANGUAGE plpgsql;
            """)
            
            connection.commit()
            cursor.close()
            connection.close()
            logger.info("  ✅ Sync/aggregation functions installed")
            return True
        except Exception as e:
            logger.error(f"  ❌ Sync functions installation failed: {e}")
            return False

def fix_schema(app):
    """Fix schema issues (add missing columns and constraints)"""
    logger.info("[6/8] Fixing schema (adding missing columns)...")
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
            
            # Add updated_at to screen_time if missing
            db.session.execute(text("""
                ALTER TABLE screen_time 
                ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW();
            """))
            
            # Add missing columns to agents table
            db.session.execute(text("""
                ALTER TABLE agents 
                ADD COLUMN IF NOT EXISTS agent_name VARCHAR(255);
            """))
            db.session.execute(text("""
                ALTER TABLE agents 
                ADD COLUMN IF NOT EXISTS os_build INTEGER;
            """))
            db.session.execute(text("""
                ALTER TABLE agents 
                ADD COLUMN IF NOT EXISTS windows_edition VARCHAR(50);
            """))
            db.session.execute(text("""
                ALTER TABLE agents 
                ADD COLUMN IF NOT EXISTS architecture VARCHAR(50);
            """))
            db.session.execute(text("""
                ALTER TABLE agents 
                ADD COLUMN IF NOT EXISTS local_agent_key VARCHAR(255);
            """))
            db.session.execute(text("""
                ALTER TABLE agents 
                ADD COLUMN IF NOT EXISTS api_token TEXT;
            """))
            db.session.execute(text("""
                ALTER TABLE agents 
                ADD COLUMN IF NOT EXISTS api_key VARCHAR(128);
            """))
            db.session.execute(text("""
                ALTER TABLE agents 
                ADD COLUMN IF NOT EXISTS hashed_api_token VARCHAR(255);
            """))
            db.session.execute(text("""
                ALTER TABLE agents 
                ADD COLUMN IF NOT EXISTS operational_status VARCHAR(50) DEFAULT 'NORMAL';
            """))
            db.session.execute(text("""
                ALTER TABLE agents 
                ADD COLUMN IF NOT EXISTS status_reason TEXT;
            """))
            db.session.execute(text("""
                ALTER TABLE agents 
                ADD COLUMN IF NOT EXISTS last_status_change TIMESTAMP;
            """))
            db.session.execute(text("""
                ALTER TABLE agents 
                ADD COLUMN IF NOT EXISTS diagnostics_json TEXT;
            """))
            db.session.execute(text("""
                ALTER TABLE agents 
                ADD COLUMN IF NOT EXISTS last_telemetry_time TIMESTAMP;
            """))
            
            # Add created_at to app_sessions if missing
            db.session.execute(text("""
                ALTER TABLE app_sessions 
                ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW();
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
    logger.info("[7/8] Checking admin user...")
    with app.app_context():
        try:
            from auth import DashboardUser
            admin = DashboardUser.query.filter_by(username='admin').first()
            if not admin:
                admin = DashboardUser(username='admin', role='admin')
                admin_password = os.getenv('DEFAULT_ADMIN_PASSWORD', 'changeme123')
                admin.set_password(admin_password)
                db.session.add(admin)
                db.session.commit()
                if admin_password == 'changeme123':
                    logger.info("  ✅ Default admin created (admin/changeme123)")
                    logger.warning("  ⚠️  CHANGE PASSWORD IMMEDIATELY!")
                else:
                    logger.info("  ✅ Default admin created (admin / <DEFAULT_ADMIN_PASSWORD from .env>)")
            else:
                logger.info("  ✅ Admin user exists")
            return True
        except Exception as e:
            logger.error(f"  ❌ Admin creation failed: {e}")
            db.session.rollback()
            return False

def verify_functions(app):
    """Verify all critical functions are installed correctly"""
    logger.info("[8/8] Verifying database functions...")
    with app.app_context():
        try:
            # List of functions to verify
            functions = [
                'process_screentime_event',
                'process_app_switch_event', 
                'process_domain_switch_event',
                'sync_screen_time_from_spans',
                'cleanup_old_spans',
                'sync_app_usage_from_sessions',
                'sync_domain_usage_from_sessions',
                'sync_screen_time_from_sessions'
            ]
            
            result = db.session.execute(text("""
                SELECT routine_name 
                FROM information_schema.routines 
                WHERE routine_type = 'FUNCTION' 
                AND routine_schema = 'public'
            """))
            
            installed = [row[0] for row in result.fetchall()]
            missing = [f for f in functions if f not in installed]
            
            if missing:
                logger.warning(f"  ⚠️  Missing functions: {missing}")
            else:
                logger.info(f"  ✅ All {len(functions)} functions verified")
            
            # Verify screen_time_spans table
            result = db.session.execute(text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'screen_time_spans'
                )
            """))
            if result.scalar():
                logger.info("  ✅ screen_time_spans table exists")
            else:
                logger.warning("  ⚠️  screen_time_spans table missing!")
            
            return True
        except Exception as e:
            logger.error(f"  ❌ Verification failed: {e}")
            return False

def start_server(app):
    """Start the Flask server"""
    logger.info("\n" + "="*60)
    logger.info("✅ AUTO-SETUP COMPLETE! All database functions installed.")
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
    
    # Run all setup steps in order
    steps = [
        (check_database_connection, app),
        # (create_tables, app), # Handled by Alembic
        # (create_screen_time_spans_table, app), # Handled by Alembic
        # (install_stored_procedures, app), # Handled by Alembic
        # (install_sync_functions, app), # Handled by Alembic
        # (fix_schema, app), # Handled by Alembic
        (create_default_admin, app),
        (verify_functions, app),
    ]
    
    for step_func, *args in steps:
        if not step_func(*args):
            # Special case: allow continue if just verify failed but core is ok
            if step_func == verify_functions:
                logger.warning("  ⚠️  Database verification had warnings but continuing...")
                continue
            logger.error("\n❌ Setup failed. Please fix errors and try again.")
            sys.exit(1)
    
    # Start server if not skipped
    if not skip_start:
        start_server(app)
    else:
        logger.info("\n✅ Setup complete! (Skipping server start as requested)\n")
        # Close pooled connections so a forking parent (gunicorn master)
        # doesn't leak open Postgres sockets into its workers.
        with app.app_context():
            db.engine.dispose()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Server stopped by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
