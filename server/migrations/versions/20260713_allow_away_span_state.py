"""allow 'away' state in screen_time_spans CHECK constraint

The agent's state machine produces 'away' spans (helper/state_detector.py
transitions to "away" on sleep gaps), and process_state_duration_event
accepts 'away' — but the screen_time_spans CHECK constraint only allowed
('active','idle','locked'), so away spans were rejected at the database and
away time was silently lost on the spans path.

The constraint name differs by which migration created the table:
    003a_create_core_tables  -> check_screen_time_spans_state
    20260129_add_screentime_spans (inline CHECK) -> screen_time_spans_state_check
Both are dropped if present, then one canonical named constraint is added.

Revision ID: 20260713_away_span_state
Revises: 20260712_screentime_delta_fn
Create Date: 2026-07-13 09:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20260713_away_span_state'
down_revision = '20260712_screentime_delta_fn'
branch_labels = None
depends_on = None

STATES_WITH_AWAY = "('active', 'idle', 'locked', 'away')"
STATES_LEGACY = "('active', 'idle', 'locked')"


def upgrade():
    op.execute("ALTER TABLE screen_time_spans DROP CONSTRAINT IF EXISTS check_screen_time_spans_state")
    op.execute("ALTER TABLE screen_time_spans DROP CONSTRAINT IF EXISTS screen_time_spans_state_check")
    op.execute(
        f"ALTER TABLE screen_time_spans ADD CONSTRAINT check_screen_time_spans_state "
        f"CHECK (state IN {STATES_WITH_AWAY})"
    )


def downgrade():
    op.execute("ALTER TABLE screen_time_spans DROP CONSTRAINT IF EXISTS check_screen_time_spans_state")
    op.execute(
        f"ALTER TABLE screen_time_spans ADD CONSTRAINT check_screen_time_spans_state "
        f"CHECK (state IN {STATES_LEGACY})"
    )
