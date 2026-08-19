"""Cap sync_app_usage_from_sessions / sync_domain_usage_from_sessions at 24h per day

Every other place in the pipeline that sums a day's worth of time caps
the result at 86400 seconds as a backstop against bad data (overlapping/
retried/pre-fix-agent session rows). These two stored procedures were the
one place in the chain that didn't.

Revision ID: 20260730_cap_usage_sync_at_24h
Revises: 20260713_away_span_state
Create Date: 2026-07-30
"""
from alembic import op

revision = '20260730_cap_usage_sync_at_24h'
down_revision = '20260713_away_span_state'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE OR REPLACE FUNCTION sync_app_usage_from_sessions(p_date DATE)
        RETURNS void AS $$
        BEGIN
            INSERT INTO app_usage (agent_id, date, app, duration_seconds, session_count, last_updated)
            SELECT
                agent_id,
                p_date,
                app,
                LEAST(COALESCE(SUM(duration_seconds), 0), 86400)::INTEGER,
                COUNT(*),
                NOW()
            FROM app_sessions
            WHERE start_time::DATE = p_date
            GROUP BY agent_id, app
            ON CONFLICT (agent_id, date, app) DO UPDATE SET
                duration_seconds = EXCLUDED.duration_seconds,
                session_count = EXCLUDED.session_count,
                last_updated = NOW();
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION sync_domain_usage_from_sessions(p_date DATE)
        RETURNS void AS $$
        BEGIN
            INSERT INTO domain_usage (agent_id, date, domain, duration_seconds, session_count, last_updated)
            SELECT
                agent_id,
                p_date,
                domain,
                LEAST(COALESCE(SUM(duration_seconds), 0), 86400)::INTEGER,
                COUNT(*),
                NOW()
            FROM domain_sessions
            WHERE start_time::DATE = p_date
            GROUP BY agent_id, domain
            ON CONFLICT (agent_id, date, domain) DO UPDATE SET
                duration_seconds = EXCLUDED.duration_seconds,
                session_count = EXCLUDED.session_count,
                last_updated = NOW();
        END;
        $$ LANGUAGE plpgsql;
    """)


def downgrade():
    op.execute("""
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
                last_updated = NOW();
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
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
                last_updated = NOW();
        END;
        $$ LANGUAGE plpgsql;
    """)
