"""
Midnight span handling tests.

ARCHITECTURE (current):
- The agent closes each day itself: _check_daily_boundary() finalizes totals
  at midnight and spans are persisted to the SQLite buffer, so spans arriving
  at the server never cross midnight by design.
- The server applies state_duration deltas additively to the day of the
  event timestamp via the process_screentime_delta stored procedure. The old
  server-side splitter (server.telemetry.state_spans._process_split_span)
  no longer exists.

Server-side tests run against the real database configured in DATABASE_URL
(created rows are cleaned up via the agents FK cascade).
"""

import pytest
import time
import uuid
import tempfile
from datetime import datetime
from pathlib import Path


# ============================================================================
# SERVER-SIDE TESTS: state_duration processing (additive, day-of-timestamp)
# ============================================================================

class TestStateDurationServerProcessing:
    """Integration tests for process_state_duration_event + stored procedure."""

    @pytest.fixture
    def test_agent(self, app_context):
        """Create a throwaway agent; FK cascade cleans its telemetry rows."""
        from extensions import db
        from sqlalchemy import text

        agent_id = str(uuid.uuid4())
        db.session.execute(
            text("INSERT INTO agents (agent_id, hostname) VALUES (:a, :h)"),
            {'a': agent_id, 'h': 'pytest-midnight'},
        )
        db.session.commit()
        yield agent_id
        db.session.rollback()
        db.session.execute(text("DELETE FROM agents WHERE agent_id = :a"),
                           {'a': agent_id})
        db.session.commit()

    def _get_screen_time_rows(self, agent_id):
        from extensions import db
        from sqlalchemy import text
        return db.session.execute(
            text("SELECT date, active_seconds, idle_seconds, locked_seconds, "
                 "COALESCE(away_seconds, 0) FROM screen_time WHERE agent_id = :a "
                 "ORDER BY date"),
            {'a': agent_id},
        ).fetchall()

    def test_state_duration_applies_to_timestamp_day(self, app_context, test_agent):
        from server_telemetry import process_state_duration_event

        resp, status = process_state_duration_event({
            'agent_id': test_agent,
            'state': 'active',
            'duration_seconds': 120,
            'timestamp': '2026-07-10T12:00:00+05:30',
        })
        assert status == 200, resp.get_json()
        assert resp.get_json()['status'] == 'success'

        rows = self._get_screen_time_rows(test_agent)
        assert len(rows) == 1
        assert str(rows[0][0]) == '2026-07-10'
        assert rows[0][1] == 120  # active_seconds

    def test_state_duration_accumulates_additively(self, app_context, test_agent):
        from server_telemetry import process_state_duration_event

        for delta in (100, 50):
            resp, status = process_state_duration_event({
                'agent_id': test_agent,
                'state': 'idle',
                'duration_seconds': delta,
                'timestamp': '2026-07-10T15:00:00+05:30',
            })
            assert status == 200

        rows = self._get_screen_time_rows(test_agent)
        assert len(rows) == 1
        assert rows[0][2] == 150  # idle accumulates, not replaces

    def test_day_attribution_is_by_utc_day(self, app_context, test_agent):
        """H-10: parse_agent_timestamp normalizes to naive UTC, so the
        screen_time day is the UTC day of the instant. An IST timestamp just
        after local midnight (00:00:10+05:30) is 18:30:10Z the previous day.

        NOTE: the agent closes its day at *agent-local* midnight, so for IST
        agents the two day definitions differ by 5.5h at the boundary - this
        divergence is a flagged design question in the telemetry audit.
        """
        from server_telemetry import process_state_duration_event

        resp, status = process_state_duration_event({
            'agent_id': test_agent,
            'state': 'locked',
            'duration_seconds': 600,
            'timestamp': '2026-07-11T00:00:10+05:30',
        })
        assert status == 200

        rows = self._get_screen_time_rows(test_agent)
        assert len(rows) == 1
        assert str(rows[0][0]) == '2026-07-10'  # UTC day, not IST day
        assert rows[0][3] == 600  # locked_seconds

    def test_away_state_accepted(self, app_context, test_agent):
        from server_telemetry import process_state_duration_event

        resp, status = process_state_duration_event({
            'agent_id': test_agent,
            'state': 'away',
            'duration_seconds': 300,
            'timestamp': '2026-07-10T09:00:00+05:30',
        })
        assert status == 200

        rows = self._get_screen_time_rows(test_agent)
        assert rows[0][4] == 300  # away_seconds

    def test_invalid_duration_ignored(self, app_context):
        """Zero/negative durations are dropped without touching the DB."""
        from server_telemetry import process_state_duration_event

        resp, status = process_state_duration_event({
            'agent_id': str(uuid.uuid4()),  # never inserted - must not matter
            'state': 'active',
            'duration_seconds': -50,
            'timestamp': '2026-07-10T12:00:00+05:30',
        })
        assert status == 200
        assert resp.get_json()['status'] == 'ignored'

    def test_unknown_state_ignored(self, app_context):
        from server_telemetry import process_state_duration_event

        resp, status = process_state_duration_event({
            'agent_id': str(uuid.uuid4()),
            'state': 'teleporting',
            'duration_seconds': 60,
            'timestamp': '2026-07-10T12:00:00+05:30',
        })
        assert status == 200
        assert resp.get_json()['status'] == 'ignored'

    def test_unregistered_agent_surfaces_error_not_silent_success(
            self, app_context):
        """The stored procedure traps SQL errors internally; the handler must
        report them (500), never claim success while dropping data."""
        from server_telemetry import process_state_duration_event

        resp, status = process_state_duration_event({
            'agent_id': str(uuid.uuid4()),  # violates agents FK
            'state': 'active',
            'duration_seconds': 60,
            'timestamp': '2026-07-10T12:00:00+05:30',
        })
        assert status == 500
        assert 'error' in resp.get_json()


# ============================================================================
# AGENT-SIDE TESTS: Span Persistence to Buffer
# ============================================================================

class TestAgentSpanPersistence:
    """Test agent persists spans to SQLite buffer before midnight reset"""

    def test_span_persisted_to_buffer(self):
        """
        Scenario: StateDetector creates span
        Expected: Span immediately persisted to SQLite buffer
        """
        from agent.core.buffer import BufferDB

        with tempfile.TemporaryDirectory() as tmpdir:
            buffer_path = Path(tmpdir) / "buffer.db"

            # Create buffer
            buffer = BufferDB(buffer_path)

            # Create test span
            test_span = {
                'span_id': 'test-agent-away-1234567890',
                'agent_id': 'test-agent-uuid',
                'state': 'away',
                'start_time': '2026-04-08T19:00:00+00:00',
                'end_time': '2026-04-08T21:00:00+00:00',
                'duration_seconds': 7200,
                'created_at': '2026-04-08T21:00:00+00:00'
            }

            # Insert span
            success = buffer.store_state_span(test_span)
            assert success == True

            # Verify span was inserted
            unuploaded = buffer.get_unuploaded_state_spans()
            assert len(unuploaded) == 1
            assert unuploaded[0]['span_id'] == test_span['span_id']
            assert unuploaded[0]['state'] == 'away'
            assert unuploaded[0]['duration_seconds'] == 7200

            # ✅ CRITICAL FIX: Close buffer to release file lock on Windows
            buffer.close()

    def test_span_idempotency(self):
        """
        Scenario: Same span inserted twice (duplicate upload)
        Expected: Second insert ignored (no duplicate)
        """
        from agent.core.buffer import BufferDB

        with tempfile.TemporaryDirectory() as tmpdir:
            buffer_path = Path(tmpdir) / "buffer.db"
            buffer = BufferDB(buffer_path)

            test_span = {
                'span_id': 'duplicate-test-span',
                'agent_id': 'test-agent',
                'state': 'locked',
                'start_time': '2026-04-08T19:00:00+00:00',
                'end_time': '2026-04-08T20:00:00+00:00',
                'duration_seconds': 3600,
                'created_at': '2026-04-08T20:00:00+00:00'
            }

            # Insert twice
            buffer.store_state_span(test_span)
            buffer.store_state_span(test_span)

            # Verify only one span exists
            unuploaded = buffer.get_unuploaded_state_spans()
            assert len(unuploaded) == 1

            # ✅ CRITICAL FIX: Close buffer to release file lock on Windows
            buffer.close()

    def test_multiple_spans_survive_reset(self):
        """
        Scenario: Multiple spans created, midnight reset occurs
        Expected: All spans remain in buffer after reset
        """
        from agent.core.buffer import BufferDB

        with tempfile.TemporaryDirectory() as tmpdir:
            buffer_path = Path(tmpdir) / "buffer.db"
            buffer = BufferDB(buffer_path)

            # Create multiple spans (simulating a day's activity)
            spans = [
                {
                    'span_id': f'test-agent-active-{i}',
                    'agent_id': 'test-agent',
                    'state': 'active',
                    'start_time': f'2026-04-08T{8+i}:00:00+00:00',
                    'end_time': f'2026-04-08T{9+i}:00:00+00:00',
                    'duration_seconds': 3600,
                    'created_at': f'2026-04-08T{9+i}:00:00+00:00'
                }
                for i in range(5)
            ]

            # Insert all spans
            for span in spans:
                buffer.store_state_span(span)

            # Simulate midnight reset (in real code, this would clear memory)
            # But buffer should retain all spans
            unuploaded = buffer.get_unuploaded_state_spans()
            assert len(unuploaded) == 5

            # Mark some as uploaded
            uploaded_ids = [s['id'] for s in unuploaded[:3]]
            buffer.mark_state_spans_uploaded(uploaded_ids)

            # Verify remaining unuploaded
            unuploaded = buffer.get_unuploaded_state_spans()
            assert len(unuploaded) == 2

            # ✅ CRITICAL FIX: Close buffer to release file lock on Windows
            buffer.close()


@pytest.fixture
def app_context():
    """Create Flask app context for server tests"""
    import os
    os.environ['FLASK_ENV'] = 'development'  # Avoid SECRET_KEY errors
    from server_app import create_app

    app = create_app()
    with app.app_context():
        yield app


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])
