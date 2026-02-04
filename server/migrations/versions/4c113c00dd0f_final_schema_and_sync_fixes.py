"""final_schema_and_sync_fixes

Revision ID: 4c113c00dd0f
Revises: 68e2644c1171
Create Date: 2026-02-03 19:44:49.879067

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4c113c00dd0f'
down_revision: Union[str, Sequence[str], None] = '68e2644c1171'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    
    # 1. Ensure agents.hashed_api_token is nullable
    op.execute("""
        ALTER TABLE agents ALTER COLUMN hashed_api_token DROP NOT NULL;
    """)
    
    # 2. Ensure extra columns exist
    op.execute("""
        DO $$
        BEGIN
            -- app_sessions.created_at
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name='app_sessions' AND column_name='created_at'
            ) THEN
                ALTER TABLE app_sessions ADD COLUMN created_at TIMESTAMP DEFAULT NOW();
            END IF;
            
            -- agent_current_status missing columns
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='agent_current_status' AND column_name='current_domain') THEN
                ALTER TABLE agent_current_status ADD COLUMN current_domain VARCHAR(255) NULL;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='agent_current_status' AND column_name='current_browser') THEN
                ALTER TABLE agent_current_status ADD COLUMN current_browser VARCHAR(100) NULL;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='agent_current_status' AND column_name='current_url') THEN
                ALTER TABLE agent_current_status ADD COLUMN current_url TEXT NULL;
            END IF;
        END $$;
    """)
    
    # 3. Fix sync_screen_time_from_sessions ambiguity
    op.execute("DROP FUNCTION IF EXISTS sync_screen_time_from_sessions(DATE);")
    op.execute("""
        CREATE OR REPLACE FUNCTION sync_screen_time_from_sessions(p_date DATE)
        RETURNS TABLE(res_agent_id UUID, synced BOOLEAN) AS $$
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


def downgrade() -> None:
    """Downgrade schema."""
    pass
