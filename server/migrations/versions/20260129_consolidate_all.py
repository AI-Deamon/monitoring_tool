"""
Consolidated Migration - All Database Schema and Procedures

This migration consolidates all scattered manual scripts into one authoritative
Alembic migration. After running this, you should NOT need to run any manual
scripts from scripts/fixes/ or scripts/migrations/.

Revision ID: 20260129_consolidate_all
Revises: c15377a4441b
Create Date: 2026-01-29 13:16:00

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20260129_consolidate_all'
down_revision = 'c15377a4441b'
branch_labels = None
depends_on = None


def upgrade():
    """
    Consolidate all manual migrations into one authoritative migration.
    This includes:
    1. Schema fixes (columns, indexes, constraints)
    2. Stored procedures (screentime, app_switch, domain_switch)
    3. Sync functions
    4. Classification setup
    """
    
    # ========================================================================
    # PART 1: SCHEMA FIXES
    # ========================================================================
    
    # Add away_seconds column if not exists
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name='screen_time' AND column_name='away_seconds'
            ) THEN
                ALTER TABLE screen_time ADD COLUMN away_seconds INTEGER DEFAULT 0;
            END IF;
        END $$;
    """)
    
    # Add source column to app_inventory if not exists
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name='app_inventory' AND column_name='source'
            ) THEN
                ALTER TABLE app_inventory ADD COLUMN source VARCHAR(50);
            END IF;
        END $$;
    """)
    
    # Add domain session columns to agent_current_status if not exists
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name='agent_current_status' AND column_name='domain_session_start'
            ) THEN
                ALTER TABLE agent_current_status ADD COLUMN domain_session_start TIMESTAMP NULL;
            END IF;
            
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name='agent_current_status' AND column_name='domain_duration_seconds'
            ) THEN
                ALTER TABLE agent_current_status ADD COLUMN domain_duration_seconds INTEGER DEFAULT 0;
            END IF;
        END $$;
    """)
    
    # Add last_telemetry_time to agents if not exists
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name='agents' AND column_name='last_telemetry_time'
            ) THEN
                ALTER TABLE agents ADD COLUMN last_telemetry_time TIMESTAMP;
                UPDATE agents SET last_telemetry_time = last_seen WHERE last_telemetry_time IS NULL AND last_seen IS NOT NULL;
            END IF;
        END $$;
    """)
    
    # ========================================================================
    # PART 2: PERFORMANCE INDEXES
    # ========================================================================
    
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_app_sessions_agent_date ON app_sessions(agent_id, start_time);
        CREATE INDEX IF NOT EXISTS idx_domain_sessions_agent_date ON domain_sessions(agent_id, start_time);
        CREATE INDEX IF NOT EXISTS idx_app_usage_agent_date ON app_usage(agent_id, date);
        CREATE INDEX IF NOT EXISTS idx_domain_usage_agent_date ON domain_usage(agent_id, date);
        CREATE INDEX IF NOT EXISTS idx_screen_time_agent_date ON screen_time(agent_id, date);
        CREATE INDEX IF NOT EXISTS idx_raw_events_received ON raw_events(agent_id, received_at, processed);
        CREATE INDEX IF NOT EXISTS idx_agent_current_status_last_seen ON agent_current_status(last_seen);
    """)
    
    # ========================================================================
    # PART 3: STORED PROCEDURES (VARCHAR-compatible)
    # ========================================================================
    
    # Process Screentime Event (with GREATEST for cumulative values)
    op.execute("""
        CREATE OR REPLACE FUNCTION process_screentime_event(
            p_agent_id VARCHAR,
            p_date DATE,
            p_username VARCHAR,
            p_active_seconds INTEGER,
            p_idle_seconds INTEGER,
            p_locked_seconds INTEGER,
            p_away_seconds INTEGER
        ) RETURNS TABLE(status text, message text) AS $$
        DECLARE
            v_existing_record RECORD;
        BEGIN
            SELECT * INTO v_existing_record
            FROM screen_time
            WHERE agent_id = p_agent_id::UUID AND date = p_date;
            
            IF FOUND THEN
                UPDATE screen_time
                SET active_seconds = GREATEST(active_seconds, p_active_seconds),
                    idle_seconds = GREATEST(idle_seconds, p_idle_seconds),
                    locked_seconds = GREATEST(locked_seconds, p_locked_seconds),
                    away_seconds = GREATEST(away_seconds, p_away_seconds),
                    username = COALESCE(p_username, username),
                    last_updated = NOW()
                WHERE agent_id = p_agent_id::UUID AND date = p_date;
                
                RETURN QUERY SELECT 'updated'::text, 'Screen time updated'::text;
            ELSE
                INSERT INTO screen_time (
                    agent_id, date, username,
                    active_seconds, idle_seconds, locked_seconds, away_seconds,
                    last_updated
                ) VALUES (
                    p_agent_id::UUID, p_date, p_username,
                    p_active_seconds, p_idle_seconds, p_locked_seconds, p_away_seconds,
                    NOW()
                );
                
                RETURN QUERY SELECT 'inserted'::text, 'Screen time created'::text;
            END IF;
        END;
        $$ LANGUAGE plpgsql;
    """)
    
    # Process App Switch Event (with duplicate detection)
    op.execute("""
        CREATE OR REPLACE FUNCTION process_app_switch_event(
            p_agent_id VARCHAR,
            p_username VARCHAR,
            p_app VARCHAR,
            p_window_title TEXT,
            p_start_time TIMESTAMP,
            p_end_time TIMESTAMP,
            p_duration_seconds INTEGER,
            p_idempotency_key VARCHAR DEFAULT NULL
        ) RETURNS TABLE(status text, message text) AS $$
        DECLARE
            v_session_date DATE;
            v_existing_session RECORD;
        BEGIN
            v_session_date := p_start_time::DATE;
            
            -- Duplicate detection
            IF p_idempotency_key IS NOT NULL THEN
                SELECT * INTO v_existing_session
                FROM app_sessions
                WHERE agent_id = p_agent_id::UUID
                  AND start_time = p_start_time
                  AND app = p_app
                LIMIT 1;
                
                IF FOUND THEN
                    RETURN QUERY SELECT 'duplicate'::text, 'Session already exists'::text;
                    RETURN;
                END IF;
            END IF;
            
            -- Insert session
            INSERT INTO app_sessions (
                agent_id, username, app, window_title,
                start_time, end_time, duration_seconds
            ) VALUES (
                p_agent_id::UUID, p_username, p_app, p_window_title,
                p_start_time, p_end_time, p_duration_seconds
            );
            
            -- Update or insert app_usage
            INSERT INTO app_usage (agent_id, date, app, duration_seconds, session_count, last_updated)
            VALUES (p_agent_id::UUID, v_session_date, p_app, p_duration_seconds, 1, NOW())
            ON CONFLICT (agent_id, date, app)
            DO UPDATE SET
                duration_seconds = app_usage.duration_seconds + EXCLUDED.duration_seconds,
                session_count = app_usage.session_count + 1,
                last_updated = NOW();
            
            RETURN QUERY SELECT 'inserted'::text, 'App session created'::text;
        END;
        $$ LANGUAGE plpgsql;
    """)
    
    # Process Domain Switch Event (with duplicate detection)
    op.execute("""
        CREATE OR REPLACE FUNCTION process_domain_switch_event(
            p_agent_id VARCHAR,
            p_username VARCHAR,
            p_domain VARCHAR,
            p_raw_title TEXT,
            p_raw_url TEXT,
            p_browser VARCHAR,
            p_start_time TIMESTAMP,
            p_end_time TIMESTAMP,
            p_duration_seconds INTEGER,
            p_idempotency_key VARCHAR DEFAULT NULL
        ) RETURNS TABLE(status text, message text) AS $$
        DECLARE
            v_session_date DATE;
            v_existing_session RECORD;
        BEGIN
            v_session_date := p_start_time::DATE;
            
            -- Duplicate detection
            IF p_idempotency_key IS NOT NULL THEN
                SELECT * INTO v_existing_session
                FROM domain_sessions
                WHERE agent_id = p_agent_id::UUID
                  AND start_time = p_start_time
                  AND domain = p_domain
                LIMIT 1;
                
                IF FOUND THEN
                    RETURN QUERY SELECT 'duplicate'::text, 'Session already exists'::text;
                    RETURN;
                END IF;
            END IF;
            
            -- Insert session
            INSERT INTO domain_sessions (
                agent_id, username, domain, raw_title, raw_url, browser,
                start_time, end_time, duration_seconds, domain_source, needs_review
            ) VALUES (
                p_agent_id::UUID, p_username, p_domain, p_raw_title, p_raw_url, p_browser,
                p_start_time, p_end_time, p_duration_seconds, 'agent', FALSE
            );
            
            -- Update or insert domain_usage
            INSERT INTO domain_usage (agent_id, date, domain, duration_seconds, session_count, last_updated)
            VALUES (p_agent_id::UUID, v_session_date, p_domain, p_duration_seconds, 1, NOW())
            ON CONFLICT (agent_id, date, domain)
            DO UPDATE SET
                duration_seconds = domain_usage.duration_seconds + EXCLUDED.duration_seconds,
                session_count = domain_usage.session_count + 1,
                last_updated = NOW();
            
            RETURN QUERY SELECT 'inserted'::text, 'Domain session created'::text;
        END;
        $$ LANGUAGE plpgsql;
    """)
    
    # ========================================================================
    # PART 4: SYNC FUNCTIONS
    # ========================================================================
    
    # Sync screen time from sessions
    op.execute("""
        CREATE OR REPLACE FUNCTION sync_screen_time_from_sessions(p_date DATE)
        RETURNS TABLE(agent_id UUID, synced BOOLEAN) AS $$
        BEGIN
            RETURN QUERY
            WITH session_totals AS (
                SELECT
                    s.agent_id,
                    SUM(s.duration_seconds) as total_seconds
                FROM app_sessions s
                WHERE s.start_time::DATE = p_date
                GROUP BY s.agent_id
            )
            INSERT INTO screen_time (agent_id, date, active_seconds, idle_seconds, locked_seconds, away_seconds, last_updated)
            SELECT st.agent_id, p_date, st.total_seconds, 0, 0, 0, NOW()
            FROM session_totals st
            ON CONFLICT (agent_id, date)
            DO UPDATE SET
                active_seconds = GREATEST(screen_time.active_seconds, EXCLUDED.active_seconds),
                last_updated = NOW()
            RETURNING screen_time.agent_id, TRUE;
        END;
        $$ LANGUAGE plpgsql;
    """)
    
    # Sync app usage from sessions
    op.execute("""
        CREATE OR REPLACE FUNCTION sync_app_usage_from_sessions(p_date DATE)
        RETURNS INTEGER AS $$
        DECLARE
            v_count INTEGER;
        BEGIN
            WITH session_totals AS (
                SELECT
                    agent_id,
                    app,
                    SUM(duration_seconds) as total_duration,
                    COUNT(*) as total_sessions
                FROM app_sessions
                WHERE start_time::DATE = p_date
                GROUP BY agent_id, app
            )
            INSERT INTO app_usage (agent_id, date, app, duration_seconds, session_count, last_updated)
            SELECT agent_id, p_date, app, total_duration, total_sessions, NOW()
            FROM session_totals
            ON CONFLICT (agent_id, date, app)
            DO UPDATE SET
                duration_seconds = EXCLUDED.duration_seconds,
                session_count = EXCLUDED.session_count,
                last_updated = NOW();
            
            GET DIAGNOSTICS v_count = ROW_COUNT;
            RETURN v_count;
        END;
        $$ LANGUAGE plpgsql;
    """)
    
    # Sync domain usage from sessions
    op.execute("""
        CREATE OR REPLACE FUNCTION sync_domain_usage_from_sessions(p_date DATE)
        RETURNS INTEGER AS $$
        DECLARE
            v_count INTEGER;
        BEGIN
            WITH session_totals AS (
                SELECT
                    agent_id,
                    domain,
                    SUM(duration_seconds) as total_duration,
                    COUNT(*) as total_sessions
                FROM domain_sessions
                WHERE start_time::DATE = p_date
                GROUP BY agent_id, domain
            )
            INSERT INTO domain_usage (agent_id, date, domain, duration_seconds, session_count, last_updated)
            SELECT agent_id, p_date, domain, total_duration, total_sessions, NOW()
            FROM session_totals
            ON CONFLICT (agent_id, date, domain)
            DO UPDATE SET
                duration_seconds = EXCLUDED.duration_seconds,
                session_count = EXCLUDED.session_count,
                last_updated = NOW();
            
            GET DIAGNOSTICS v_count = ROW_COUNT;
            RETURN v_count;
        END;
        $$ LANGUAGE plpgsql;
    """)
    
    print("✓ Consolidated migration applied successfully!")


def downgrade():
    """
    Downgrade is intentionally minimal - we don't want to drop data.
    Only drop the stored procedures.
    """
    op.execute("DROP FUNCTION IF EXISTS process_screentime_event CASCADE;")
    op.execute("DROP FUNCTION IF EXISTS process_app_switch_event CASCADE;")
    op.execute("DROP FUNCTION IF EXISTS process_domain_switch_event CASCADE;")
    op.execute("DROP FUNCTION IF EXISTS sync_screen_time_from_sessions CASCADE;")
    op.execute("DROP FUNCTION IF EXISTS sync_app_usage_from_sessions CASCADE;")
    op.execute("DROP FUNCTION IF EXISTS sync_domain_usage_from_sessions CASCADE;")
    
    print("✓ Stored procedures removed")
