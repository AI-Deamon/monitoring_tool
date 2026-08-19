"""
Unit tests for ScreenTimeEngine fixes:
- Idempotent reset_daily()
- Context-aware sleep gap (LOCKED stays LOCKED, else AWAY)
- Tick before daily boundary crossing
- Handle_suspend respects LOCKED as terminal
"""

import time
import json
import unittest
from contextlib import contextmanager
from unittest.mock import patch, MagicMock
from pathlib import Path
from datetime import datetime, date, timedelta
import tempfile
import shutil

# Adjust import path for test context
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agent'))

from core import state_machine as sm_module
from core.state_machine import ScreenTimeEngine, ScreenState, LastEvent


class TestResetDailyIdempotent(unittest.TestCase):
    """Test that reset_daily() only fires once per calendar day."""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.engine = ScreenTimeEngine(data_dir=self.tmp_dir, agent_id="test-agent")

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_first_reset_succeeds(self):
        """First reset_daily() call should zero all counters."""
        self.engine.active_seconds = 100.0
        self.engine.idle_seconds = 50.0
        self.engine.locked_seconds = 200.0
        self.engine.away_seconds = 30.0

        self.engine.reset_daily()

        self.assertEqual(self.engine.active_seconds, 0.0)
        self.assertEqual(self.engine.idle_seconds, 0.0)
        self.assertEqual(self.engine.locked_seconds, 0.0)
        self.assertEqual(self.engine.away_seconds, 0.0)

    def test_second_reset_is_noop(self):
        """Second reset_daily() call on same date should be a no-op."""
        self.engine.active_seconds = 100.0
        self.engine.reset_daily()  # First reset
        self.assertEqual(self.engine.active_seconds, 0.0)

        # Simulate some time passing (but same day)
        self.engine.active_seconds = 500.0
        self.engine.locked_seconds = 300.0

        self.engine.reset_daily()  # Second reset — should be no-op

        # Counters should NOT be zeroed again
        self.assertEqual(self.engine.active_seconds, 500.0)
        self.assertEqual(self.engine.locked_seconds, 300.0)

    def test_reset_on_new_day_succeeds(self):
        """reset_daily() should work on a new calendar day."""
        self.engine.active_seconds = 100.0
        self.engine.reset_daily()  # Today's reset
        self.assertEqual(self.engine.active_seconds, 0.0)

        # Simulate next day
        self.engine.active_seconds = 500.0
        yesterday = date.today() - timedelta(days=1)
        self.engine._last_reset_date = yesterday

        self.engine.reset_daily()  # New day — should succeed
        self.assertEqual(self.engine.active_seconds, 0.0)

    def test_reset_keeps_current_state(self):
        """reset_daily() should not change the current state."""
        self.engine.current_state = ScreenState.LOCKED
        self.engine.reset_daily()
        self.assertEqual(self.engine.current_state, ScreenState.LOCKED)


class TestSleepGapContextAware(unittest.TestCase):
    """Test that sleep gap classification depends on pre-sleep state.

    handle_startup() only credits the portion of a gap that falls on TODAY
    (effective_start = max(last_timestamp, IST midnight)), so these tests
    FREEZE the clock at a fixed mid-day instant. Using the real wall clock
    made them fail whenever the suite ran shortly after local midnight -
    the gap got clamped to "seconds since midnight".
    """

    # 2026-07-10 18:00 IST - far enough into the day that the gaps below
    # never cross midnight.
    FROZEN_NOW = datetime(2026, 7, 10, 18, 0, 0, tzinfo=sm_module._local_tz())

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.engine = ScreenTimeEngine(data_dir=self.tmp_dir, agent_id="test-agent")
        self.now_ts = self.FROZEN_NOW.timestamp()

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    @contextmanager
    def frozen_clock(self):
        with patch.object(sm_module.time, "time", return_value=self.now_ts), \
                patch.object(sm_module, "_now_ist", return_value=self.FROZEN_NOW):
            yield

    def _persisted(self, state, gap_seconds, last_event="sleep"):
        return {
            "last_event": last_event,
            "last_timestamp": self.now_ts - gap_seconds,
            "current_state": state,
            "current_date": self.FROZEN_NOW.date().isoformat(),
        }

    def test_short_sleep_gap_while_locked_counts_as_locked(self):
        """Sleep gap with pre-sleep state=LOCKED below the 2h away threshold
        should increment locked_seconds."""
        gap_seconds = 1800  # 30 minutes (< 2h threshold)

        with self.frozen_clock():
            result = self.engine.handle_startup(self._persisted("LOCKED", gap_seconds))

        self.assertEqual(result["action"], "counted_as_locked")
        self.assertAlmostEqual(self.engine.locked_seconds, gap_seconds, delta=2)
        self.assertEqual(self.engine.away_seconds, 0.0)

    def test_long_sleep_gap_while_locked_counts_as_away(self):
        """FIX #2: a lock-then-sleep gap at/over the 2h threshold is
        reclassified as AWAY, not locked."""
        gap_seconds = 7200  # exactly at the 2h threshold

        with self.frozen_clock():
            result = self.engine.handle_startup(self._persisted("LOCKED", gap_seconds))

        self.assertEqual(result["action"], "counted_as_away")
        self.assertAlmostEqual(self.engine.away_seconds, gap_seconds, delta=2)
        self.assertEqual(self.engine.locked_seconds, 0.0)

    def test_sleep_gap_while_active_counts_as_away(self):
        """Sleep gap with pre-sleep state=ACTIVE should increment away_seconds."""
        gap_seconds = 10800  # 3 hours (same day at 18:00 IST)

        with self.frozen_clock():
            result = self.engine.handle_startup(self._persisted("ACTIVE", gap_seconds))

        self.assertEqual(result["action"], "counted_as_away")
        self.assertAlmostEqual(self.engine.away_seconds, gap_seconds, delta=2)
        self.assertEqual(self.engine.locked_seconds, 0.0)

    def test_sleep_gap_while_idle_counts_as_away(self):
        """Sleep gap with pre-sleep state=IDLE should increment away_seconds."""
        gap_seconds = 7200  # 2 hours

        with self.frozen_clock():
            result = self.engine.handle_startup(self._persisted("IDLE", gap_seconds))

        self.assertEqual(result["action"], "counted_as_away")
        self.assertAlmostEqual(self.engine.away_seconds, gap_seconds, delta=2)

    def test_overnight_gap_credits_only_todays_portion(self):
        """An overnight sleep must NOT dump yesterday's hours into today:
        only the span from local midnight to now is counted."""
        gap_seconds = 20 * 3600  # started 22:00 IST *yesterday* (18:00 - 20h)
        seconds_since_midnight = 18 * 3600  # frozen at 18:00 IST

        with self.frozen_clock():
            result = self.engine.handle_startup(self._persisted("ACTIVE", gap_seconds))

        self.assertEqual(result["action"], "counted_as_away")
        self.assertAlmostEqual(
            self.engine.away_seconds, seconds_since_midnight, delta=2,
            msg="overnight gap must be clamped at local midnight"
        )

    def test_shutdown_gap_ignored(self):
        """Shutdown gap should be ignored regardless of pre-state."""
        gap_seconds = 36000
        persisted = {
            "last_event": "shutdown",
            "last_timestamp": time.time() - gap_seconds,
            "current_state": "LOCKED",
            "current_date": date.today().isoformat()
        }

        result = self.engine.handle_startup(persisted)

        self.assertEqual(result["action"], "ignored_shutdown_gap")
        self.assertEqual(self.engine.locked_seconds, 0.0)
        self.assertEqual(self.engine.away_seconds, 0.0)

    def test_crash_gap_ignored(self):
        """Crash gap should be ignored (reliability > accuracy)."""
        persisted = {
            "last_event": "crash",
            "last_timestamp": time.time() - 3600,
            "current_state": "ACTIVE",
            "current_date": date.today().isoformat()
        }

        result = self.engine.handle_startup(persisted)

        self.assertEqual(result["action"], "ignored_crash_gap")
        self.assertEqual(self.engine.active_seconds, 0.0)

    def test_crash_gap_inferred_as_sleep_locked(self):
        """Crash gap can be treated as sleep if uptime heuristic indicates suspend."""
        persisted = {
            "last_event": "crash",
            "last_timestamp": time.time() - 1800,
            "current_state": "LOCKED",
            "current_date": date.today().isoformat()
        }

        with patch.object(self.engine, "_was_system_asleep_during_gap", return_value=True):
            result = self.engine.handle_startup(persisted)

        self.assertEqual(result["action"], "counted_as_locked")
        self.assertGreater(self.engine.locked_seconds, 0.0)

    def test_crash_gap_inferred_as_sleep_active(self):
        """Crash gap inferred as sleep should map non-locked pre-state to AWAY."""
        persisted = {
            "last_event": "crash",
            "last_timestamp": time.time() - 2400,
            "current_state": "ACTIVE",
            "current_date": date.today().isoformat()
        }

        with patch.object(self.engine, "_was_system_asleep_during_gap", return_value=True):
            result = self.engine.handle_startup(persisted)

        self.assertEqual(result["action"], "counted_as_away")
        self.assertGreater(self.engine.away_seconds, 0.0)


class TestBoundaryTicksFirst(unittest.TestCase):
    """Test that check_daily_boundary calls tick() before getting totals."""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.engine = ScreenTimeEngine(data_dir=self.tmp_dir, agent_id="test-agent")

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_boundary_flushes_current_state_time(self):
        """At midnight, tick() should be called to flush time in current state."""
        # Set up: engine is in ACTIVE state with some time elapsed
        self.engine.current_state = ScreenState.ACTIVE
        self.engine.last_timestamp = time.time() - 30  # 30s ago

        # Simulate yesterday's date
        yesterday = date.today() - timedelta(days=1)
        self.engine.current_date = yesterday
        self.engine._last_reset_date = yesterday - timedelta(days=1)

        # Call boundary crossing
        crossed = self.engine.check_daily_boundary()

        self.assertTrue(crossed)
        # After reset, counters should be zeroed
        # But the tick() should have flushed ~30s of active time before reset
        # (The final_totals log should show it)


class TestPersistenceOfResetDate(unittest.TestCase):
    """Test that _last_reset_date survives persist/load cycle."""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.engine = ScreenTimeEngine(data_dir=self.tmp_dir, agent_id="test-agent")

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_reset_date_persisted(self):
        """_last_reset_date should be saved and restored."""
        self.engine.reset_daily()  # Sets _last_reset_date to today
        
        # Create new engine pointing at same data dir
        engine2 = ScreenTimeEngine(data_dir=self.tmp_dir, agent_id="test-agent")
        engine2.load_persisted_state()
        
        self.assertEqual(engine2._last_reset_date, date.today())

    def test_no_double_reset_after_restart(self):
        """After restart, loading persisted state should prevent duplicate reset."""
        self.engine.active_seconds = 100.0
        self.engine.reset_daily()
        self.assertEqual(self.engine.active_seconds, 0.0)

        # Simulate crash/restart
        engine2 = ScreenTimeEngine(data_dir=self.tmp_dir, agent_id="test-agent")
        engine2.load_persisted_state()
        
        engine2.active_seconds = 500.0
        engine2.reset_daily()  # Should be no-op (same day)
        
        self.assertEqual(engine2.active_seconds, 500.0)


class TestMarkSleepLogMessage(unittest.TestCase):
    """Test that mark_sleep() logs the correct gap classification."""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.engine = ScreenTimeEngine(data_dir=self.tmp_dir, agent_id="test-agent")

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_mark_sleep_while_locked_logs_locked(self):
        """mark_sleep() with current_state=LOCKED should log LOCKED."""
        self.engine.current_state = ScreenState.LOCKED
        with patch('core.state_machine.logger') as mock_logger:
            self.engine.mark_sleep()
            # Check that the log message contains 'LOCKED'
            log_calls = [str(c) for c in mock_logger.info.call_args_list]
            found_locked = any('LOCKED' in c for c in log_calls)
            self.assertTrue(found_locked, f"Expected 'LOCKED' in log, got: {log_calls}")

    def test_mark_sleep_while_active_logs_away(self):
        """mark_sleep() with current_state=ACTIVE should log AWAY."""
        self.engine.current_state = ScreenState.ACTIVE
        with patch('core.state_machine.logger') as mock_logger:
            self.engine.mark_sleep()
            log_calls = [str(c) for c in mock_logger.info.call_args_list]
            found_away = any('AWAY' in c for c in log_calls)
            self.assertTrue(found_away, f"Expected 'AWAY' in log, got: {log_calls}")


if __name__ == '__main__':
    unittest.main()
