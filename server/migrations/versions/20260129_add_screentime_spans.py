"""
Alembic migration: Add screen time spans architecture

Revision ID: add_screentime_spans
Revises: 20260129_consolidate_all
Create Date: 2026-01-29 16:47:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = 'add_screentime_spans'
down_revision = '20260129_consolidate_all'
branch_labels = None
depends_on = None


def upgrade():
    # ========================================================================
    # PART 1: Create screen_time_spans table
    # ========================================================================
    op.execute("""
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
        )
    """)
    
    # Indexes for performance
    op.execute("CREATE INDEX IF NOT EXISTS idx_spans_agent_date ON screen_time_spans(agent_id, start_time)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_spans_processed ON screen_time_spans(processed) WHERE NOT processed")
    op.execute("CREATE INDEX IF NOT EXISTS idx_spans_span_id ON screen_time_spans(span_id)")
    
    # ========================================================================
    # PART 2: Aggregation stored procedure (DISABLED)
    # ========================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION sync_screen_time_from_spans(p_date DATE DEFAULT CURRENT_DATE)
        RETURNS TABLE(ret_agent_id UUID, synced BOOLEAN) AS $$
        BEGIN
            -- This function intentionally does nothing
            -- Screen time is now agent-authoritative only
            -- Spans are for timeline visualization only
            RETURN;
        END;
        $$ LANGUAGE plpgsql;
    """)
    
    # ========================================================================
    # PART 3: Data retention cleanup function
    # ========================================================================
    op.execute("""
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


def downgrade():
    # Drop functions
    op.execute("DROP FUNCTION IF EXISTS cleanup_old_spans() CASCADE")
    op.execute("DROP FUNCTION IF EXISTS sync_screen_time_from_spans(DATE) CASCADE")
    
    # Drop table
    op.execute("DROP TABLE IF EXISTS screen_time_spans CASCADE")
