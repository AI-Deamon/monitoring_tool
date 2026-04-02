"""fix app_switch deduplication logic

Revision ID: 20260401_fix_dedup
Revises: 20260303_auto_update
Create Date: 2026-04-01 13:25:00.000000

Fixes HTTP 500 error on /telemetry/app-switch caused by duplicate key
violations that were not being caught by the stored procedure.

The migration 7204218e0a8e_align_procedure_signatures.py overwrote the
deduplication logic from 20250218_add_deduplication.py. This migration
restores the proper EXCEPTION WHEN unique_violation handling.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers
revision = '20260401_fix_dedup'
down_revision = '20260303_auto_update'
branch_labels = None
depends_on = None


def upgrade():
    """Fix process_app_switch_event to handle duplicate key violations gracefully."""
    
    op.execute(text("""
        CREATE OR REPLACE FUNCTION process_app_switch_event(
            p_agent_id VARCHAR,
            p_timestamp TIMESTAMP,
            p_app VARCHAR,
            p_friendly_name VARCHAR,
            p_category VARCHAR,
            p_window_title VARCHAR,
            p_session_start TIMESTAMP,
            p_session_end TIMESTAMP,
            p_total_seconds FLOAT
        ) RETURNS TABLE(status text, message text) AS $$
        DECLARE
            v_date DATE;
        BEGIN
            v_date := p_session_start::DATE;
            
            -- Reject NULL or empty app name
            IF p_app IS NULL OR p_app = '' THEN
                RETURN QUERY SELECT 'skipped'::TEXT, 'NULL or empty app name'::TEXT;
                RETURN;
            END IF;
            
            -- Reject negative durations
            IF p_total_seconds < 0 THEN
                RETURN QUERY SELECT 'error'::TEXT, 'Negative duration rejected'::TEXT;
                RETURN;
            END IF;
            
            -- Reject excessive durations (> 8 hours = 28800 seconds)
            IF p_total_seconds > 28800 THEN
                RETURN QUERY SELECT 'skipped'::TEXT, 
                    format('Excessive duration rejected (%s hours)', round((p_total_seconds/3600.0)::numeric, 1))::TEXT;
                RETURN;
            END IF;
            
            -- Try to insert into app_sessions with deduplication handling
            -- The unique constraint uq_app_sessions_agent_app_start on (agent_id, app, start_time)
            -- prevents duplicate sessions. On conflict, we skip gracefully instead of erroring.
            BEGIN
                INSERT INTO app_sessions (
                    agent_id, app, window_title, start_time, end_time, duration_seconds, created_at
                ) VALUES (
                    p_agent_id::UUID, p_app, p_window_title, p_session_start, p_session_end, p_total_seconds, NOW()
                );
            EXCEPTION WHEN unique_violation THEN
                -- Duplicate session detected - skip gracefully (agent may retry on network failure)
                RETURN QUERY SELECT 'skipped'::text, 'Duplicate session ignored'::text;
                RETURN;
            END;
            
            -- Only update app_usage if session was successfully inserted
            INSERT INTO app_usage (
                agent_id, date, app, duration_seconds, session_count, last_updated
            ) VALUES (
                p_agent_id::UUID, v_date, p_app, p_total_seconds::INTEGER, 1, NOW()
            )
            ON CONFLICT (agent_id, date, app) DO UPDATE SET
                duration_seconds = app_usage.duration_seconds + EXCLUDED.duration_seconds,
                session_count = app_usage.session_count + 1,
                last_updated = NOW();
                
            RETURN QUERY SELECT 'success'::text, 'App switch processed'::text;
        EXCEPTION WHEN OTHERS THEN
            RETURN QUERY SELECT 'error'::text, SQLERRM::text;
        END;
        $$ LANGUAGE plpgsql;
    """))


def downgrade():
    """Restore the broken version without deduplication handling."""
    
    op.execute(text("""
        CREATE OR REPLACE FUNCTION process_app_switch_event(
            p_agent_id VARCHAR,
            p_timestamp TIMESTAMP,
            p_app VARCHAR,
            p_friendly_name VARCHAR,
            p_category VARCHAR,
            p_window_title VARCHAR,
            p_session_start TIMESTAMP,
            p_session_end TIMESTAMP,
            p_total_seconds FLOAT
        ) RETURNS TABLE(status text, message text) AS $$
        DECLARE
            v_date DATE;
        BEGIN
            v_date := p_session_start::DATE;
            
            INSERT INTO app_sessions (
                agent_id, app, window_title, start_time, end_time, duration_seconds, created_at
            ) VALUES (
                p_agent_id::UUID, p_app, p_window_title, p_session_start, p_session_end, p_total_seconds, NOW()
            );
            
            INSERT INTO app_usage (
                agent_id, date, app, duration_seconds, session_count, last_updated
            ) VALUES (
                p_agent_id::UUID, v_date, p_app, p_total_seconds::INTEGER, 1, NOW()
            )
            ON CONFLICT (agent_id, date, app) DO UPDATE SET
                duration_seconds = app_usage.duration_seconds + EXCLUDED.duration_seconds,
                session_count = app_usage.session_count + 1,
                last_updated = NOW();
                
            RETURN QUERY SELECT 'success'::text, 'App switch processed'::text;
        EXCEPTION WHEN OTHERS THEN
            RETURN QUERY SELECT 'error'::text, SQLERRM::text;
        END;
        $$ LANGUAGE plpgsql;
    """))