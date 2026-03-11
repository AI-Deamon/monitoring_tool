"""Add email field and password reset functionality

Revision ID: 20260227_password_reset
Revises: 20260227_screentime_daily_cap_guard
Create Date: 2026-02-27 12:45:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers
revision = '20260227_password_reset'
down_revision = '20260227_daily_cap'
branch_labels = None
depends_on = None

def upgrade():
    # Guard: dashboard_users may not exist on fresh DBs
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'dashboard_users') THEN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'dashboard_users' AND column_name = 'email'
                ) THEN
                    ALTER TABLE dashboard_users ADD COLUMN email VARCHAR(255);
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'dashboard_users' AND column_name = 'email_verified'
                ) THEN
                    ALTER TABLE dashboard_users ADD COLUMN email_verified BOOLEAN DEFAULT FALSE;
                END IF;
            END IF;
        END $$;
    """)
    
    # Create password_reset_tokens table (safe — uses create_table)
    op.execute("""
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            token_hash VARCHAR(255) NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            used_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_token_hash ON password_reset_tokens(token_hash)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_expires_at ON password_reset_tokens(expires_at)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_prt_user_id ON password_reset_tokens(user_id)")
    
    # Add FK only if dashboard_users exists
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'dashboard_users') THEN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.table_constraints
                    WHERE constraint_name = 'fk_prt_user_id' AND table_name = 'password_reset_tokens'
                ) THEN
                    ALTER TABLE password_reset_tokens
                        ADD CONSTRAINT fk_prt_user_id FOREIGN KEY (user_id)
                        REFERENCES dashboard_users(id) ON DELETE CASCADE;
                END IF;
            END IF;
        END $$;
    """)

def downgrade():
    op.execute("DROP TABLE IF EXISTS password_reset_tokens")
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'dashboard_users') THEN
                ALTER TABLE dashboard_users DROP COLUMN IF EXISTS email_verified;
                ALTER TABLE dashboard_users DROP COLUMN IF EXISTS email;
            END IF;
        END $$;
    """)
