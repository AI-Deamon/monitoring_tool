"""Add indexes for telemetry tables

Revision ID: 20260619_telemetry_indexes
Revises: 20260618_agent_unique
Create Date: 2026-06-19

H-14 FIX: Add indexes on frequently queried columns to improve query performance.
Targets: date, agent_id, username columns in telemetry tables.
"""
from alembic import op
import sqlalchemy as sa

revision = '20260619_telemetry_indexes'
down_revision = '20260618_agent_unique'
branch_labels = None
depends_on = None


def upgrade():
    # IF NOT EXISTS throughout: several of these overlap indexes created by
    # earlier migrations (e.g. ix_raw_events_processed in 003a), and this
    # migration previously crashed every upgrade by indexing
    # screen_time_spans.username — a column no migration creates. That index
    # is intentionally gone; nothing queries spans by username.
    op.execute("CREATE INDEX IF NOT EXISTS ix_screen_time_agent_date ON screen_time (agent_id, date)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_screen_time_username ON screen_time (username)")

    op.execute("CREATE INDEX IF NOT EXISTS ix_screen_time_spans_agent_start ON screen_time_spans (agent_id, start_time)")

    op.execute("CREATE INDEX IF NOT EXISTS ix_app_usage_agent_date ON app_usage (agent_id, date)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_app_usage_username ON app_usage (username)")

    op.execute("CREATE INDEX IF NOT EXISTS ix_domain_usage_agent_date ON domain_usage (agent_id, date)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_domain_usage_username ON domain_usage (username)")

    op.execute("CREATE INDEX IF NOT EXISTS ix_raw_events_agent_received ON raw_events (agent_id, received_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_raw_events_processed ON raw_events (processed)")


def downgrade():
    # Remove indexes in reverse order. ix_raw_events_processed is left in
    # place: 003a also creates it, so it predates this migration.
    op.execute("DROP INDEX IF EXISTS ix_raw_events_agent_received")

    op.execute("DROP INDEX IF EXISTS ix_domain_usage_username")
    op.execute("DROP INDEX IF EXISTS ix_domain_usage_agent_date")

    op.execute("DROP INDEX IF EXISTS ix_app_usage_username")
    op.execute("DROP INDEX IF EXISTS ix_app_usage_agent_date")

    op.execute("DROP INDEX IF EXISTS ix_screen_time_spans_agent_start")

    op.execute("DROP INDEX IF EXISTS ix_screen_time_username")
    op.execute("DROP INDEX IF EXISTS ix_screen_time_agent_date")
