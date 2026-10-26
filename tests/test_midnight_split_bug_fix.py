"""
Unit tests for Midnight Split & Persist Race Bug Fixes:
1. Overnight lock boundary split (Day 1 gets pre-midnight only, Day 2 gets post-midnight).
2. Multi-day suspend gap rollover.
3. Atomic persist with unique temp filename and retries.
"""

import time
import json
import unittest
from contextlib import contextmanager
from unittest.mock import patch
from pathlib import Path
from datetime import datetime, date, timedelta
import tempfile
import shutil

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agent'))

from core import state_machine as sm_module
from core.state_machine import ScreenTimeEngine, ScreenState, LastEvent


class TestMidnightSplitFix(unittest.TestCase):
    """Test that check_daily_boundary correctly splits time at midnight."""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.engine = ScreenTimeEngine(data_dir=self.tmp_dir, agent_id="test-agent")

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_overnight_lock_splits_cleanly_between_dates(self):
        """
        Scenario:
        User locks screen at 23:30 on Day 1 (Oct 20).
        Engine ticks or suspends at 02:11 on Day 2 (Oct 21).
        
        Expected:
        - Day 1 final totals: exactly 1800s (30m) of locked time.
        - Day 2 totals: exactly 7860s (~2h 11m) of AWAY time (since 2h+ threshold reached).
        - Day 1 totals DO NOT include the post-midnight 2h 11m.
        """
        tz = sm_module._local_tz()
        day1_date = date(2026, 10, 20)
        day2_date = date(2026, 10, 21)

        # 23:30 on Day 1
        lock_dt = datetime(2026, 10, 20, 23, 30, 0, tzinfo=tz)
        lock_ts = lock_dt.timestamp()

        # 02:11 on Day 2
        tick_dt = datetime(2026, 10, 21, 2, 11, 0, tzinfo=tz)
        tick_ts = tick_dt.timestamp()

        # Set engine initial state at 23:30 on Day 1
        self.engine.current_date = day1_date
        self.engine.current_state = ScreenState.LOCKED
        self.engine.last_timestamp = lock_ts
        self.engine.locked_seconds = 0.0
        self.engine.away_seconds = 0.0
        self.engine.pending_locked_seconds = 0.0

        # Simulate time moving to 02:11 on Day 2
        with patch.object(sm_module.time, "time", return_value=tick_ts), \
             patch.object(sm_module, "_now_ist", return_value=tick_dt):
            crossed, final_totals = self.engine.check_daily_boundary()

        self.assertTrue(crossed)
        self.assertIsNotNone(final_totals)

        # Day 1 final totals must ONLY have the 30 min (1800s) from 23:30 to 00:00
        # (30m < 2h threshold, so it classifies as locked)
        self.assertEqual(final_totals["locked_seconds"], 1800)
        self.assertEqual(final_totals["away_seconds"], 0)
        self.assertEqual(final_totals["total_seconds"], 1800)

        # Day 2 current totals must have 00:00 to 02:11 = 2h 11m = 7860s
        # Since 7860s >= 7200s (2h threshold), it must be classified as AWAY
        day2_totals = self.engine.get_daily_totals()
        self.assertEqual(self.engine.current_date, day2_date)
        self.assertEqual(day2_totals["locked_seconds"], 0)
        self.assertEqual(day2_totals["away_seconds"], 7860)
        self.assertEqual(day2_totals["total_seconds"], 7860)

    def test_tick_across_midnight_delegates_to_boundary(self):
        """If tick() is called across midnight, it should automatically trigger boundary rollover."""
        tz = sm_module._local_tz()
        day1_date = date(2026, 10, 20)
        day2_date = date(2026, 10, 21)

        lock_dt = datetime(2026, 10, 20, 23, 45, 0, tzinfo=tz)
        lock_ts = lock_dt.timestamp()

        tick_dt = datetime(2026, 10, 21, 1, 0, 0, tzinfo=tz)
        tick_ts = tick_dt.timestamp()

        self.engine.current_date = day1_date
        self.engine.current_state = ScreenState.LOCKED
        self.engine.last_timestamp = lock_ts

        with patch.object(sm_module.time, "time", return_value=tick_ts), \
             patch.object(sm_module, "_now_ist", return_value=tick_dt):
            self.engine.tick()

        # Current date updated to Day 2
        self.assertEqual(self.engine.current_date, day2_date)

        # Day 2 totals: 00:00 to 01:00 = 3600s
        # 3600s < 7200s threshold -> classified as locked
        day2_totals = self.engine.get_daily_totals()
        self.assertEqual(day2_totals["locked_seconds"], 3600)

        # Pending final totals can be retrieved via check_daily_boundary()
        with patch.object(sm_module.time, "time", return_value=tick_ts), \
             patch.object(sm_module, "_now_ist", return_value=tick_dt):
            crossed, final_totals = self.engine.check_daily_boundary()

        self.assertTrue(crossed)
        self.assertIsNotNone(final_totals)
        # Day 1 had 15 min (900s)
        self.assertEqual(final_totals["locked_seconds"], 900)

    def test_multi_day_gap_advances_day_by_day(self):
        """Simulate a 3-day sleep gap (Friday night to Monday morning)."""
        tz = sm_module._local_tz()
        fri_dt = datetime(2026, 10, 16, 23, 0, 0, tzinfo=tz)
        mon_dt = datetime(2026, 10, 19, 9, 0, 0, tzinfo=tz)

        self.engine.current_date = date(2026, 10, 16)
        self.engine.current_state = ScreenState.LOCKED
        self.engine.last_timestamp = fri_dt.timestamp()

        with patch.object(sm_module.time, "time", return_value=mon_dt.timestamp()), \
             patch.object(sm_module, "_now_ist", return_value=mon_dt):
            crossed, final_totals = self.engine.check_daily_boundary()

        self.assertTrue(crossed)
        self.assertEqual(self.engine.current_date, date(2026, 10, 19))

        # Monday totals should be 00:00 to 09:00 = 9h = 32400s (AWAY)
        day_totals = self.engine.get_daily_totals()
        self.assertEqual(day_totals["away_seconds"], 32400)


class TestPersistRaceFix(unittest.TestCase):
    """Test that _persist() is resilient against rapid calls."""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.engine = ScreenTimeEngine(data_dir=self.tmp_dir, agent_id="test-agent")

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_rapid_persist_calls_do_not_crash(self):
        """Rapid successive _persist calls should all succeed without WinError 32."""
        for i in range(50):
            self.engine.active_seconds = float(i)
            self.engine._persist()

        # Verify state file is valid JSON and matches last persisted value
        self.assertTrue(self.engine.state_file.exists())
        with open(self.engine.state_file, "r") as f:
            data = json.load(f)
        self.assertEqual(data["active_seconds"], 49.0)


class TestRebootDuringGapInferredAsShutdown(unittest.TestCase):
    """Test that if the system rebooted during a gap (even with last_event='normal'), it is treated as a shutdown."""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.engine = ScreenTimeEngine(data_dir=self.tmp_dir, agent_id="test-agent")

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_unclean_shutdown_over_weekend_inferred_as_shutdown(self):
        """
        Scenario from user logs:
        - Oct 16 (Friday) 18:47: user locked and shut down laptop.
        - Windows killed agent before mark_shutdown() ran -> last_event='normal', state='LOCKED'.
        - Oct 21 (Wednesday) 10:18: laptop booted up fresh (boot_time = Oct 21 10:17).
        
        Expected:
        - Since boot_time > last_timestamp, handle_startup recognizes the reboot.
        - Gap is ignored ('ignored_shutdown_gap').
        - Away seconds remains 0.0 (NO 10.3h of fake away time).
        """
        tz = sm_module._local_tz()
        fri_dt = datetime(2026, 10, 16, 18, 47, 27, tzinfo=tz)
        fri_ts = fri_dt.timestamp()

        wed_dt = datetime(2026, 10, 21, 10, 18, 39, tzinfo=tz)
        wed_ts = wed_dt.timestamp()

        # Laptop was booted 1 minute before agent started on Wednesday
        wed_boot_ts = wed_ts - 60.0

        persisted = {
            "current_state": "LOCKED",
            "last_event": "normal",
            "last_timestamp": fri_ts,
            "current_date": "2026-10-16",
            "active_seconds": 100.0,
            "locked_seconds": 50.0,
            "away_seconds": 0.0,
            "pending_locked_seconds": 0.0,
        }

        with patch.object(sm_module.time, "time", return_value=wed_ts), \
             patch.object(sm_module, "_now_ist", return_value=wed_dt), \
             patch.object(self.engine, "_get_system_boot_time", return_value=wed_boot_ts):
            result = self.engine.handle_startup(persisted)

        self.assertEqual(result["action"], "ignored_shutdown_gap")
        self.assertEqual(self.engine.away_seconds, 0.0)
        self.assertEqual(self.engine.locked_seconds, 0.0)

    def test_lock_session_exceeding_2h_routes_all_subsequent_time_to_away(self):
        """
        Scenario 1 Fix:
        When a user locks their screen for 2 hours 45 minutes:
        - At 2h: 7200s escalates to AWAY, pending_locked_seconds is reset.
        - Next 45m: accrues directly to AWAY, NOT to pending_locked_seconds.
        - On unlock: 0s leaked into locked_seconds.
        - Total: away_seconds = 9900s (2h 45m), locked_seconds = 0s.
        """
        now = 1700000000.0
        with patch.object(sm_module.time, "time", return_value=now):
            self.engine.last_timestamp = now
            self.engine.transition(ScreenState.LOCKED)
        self.assertFalse(self.engine._is_lock_escalated_to_away)
        self.assertEqual(self.engine.pending_locked_seconds, 0.0)

        # 1 hour passes (3600s) -> pending = 3600, away = 0
        now += 3600.0
        with patch.object(sm_module.time, "time", return_value=now):
            self.engine.tick()
        self.assertFalse(self.engine._is_lock_escalated_to_away)
        self.assertEqual(self.engine.pending_locked_seconds, 3600.0)
        self.assertEqual(self.engine.away_seconds, 0.0)

        # Another 1 hour passes (now at 2 hours total = 7200s) -> escalates to AWAY
        now += 3600.0
        with patch.object(sm_module.time, "time", return_value=now):
            self.engine.tick()
        self.assertTrue(self.engine._is_lock_escalated_to_away)
        self.assertEqual(self.engine.pending_locked_seconds, 0.0)
        self.assertEqual(self.engine.away_seconds, 7200.0)
        self.assertEqual(self.engine.locked_seconds, 0.0)

        # Another 45 minutes pass (2700s) while still LOCKED
        now += 2700.0
        with patch.object(sm_module.time, "time", return_value=now):
            self.engine.tick()
        self.assertTrue(self.engine._is_lock_escalated_to_away)
        self.assertEqual(self.engine.pending_locked_seconds, 0.0)
        self.assertEqual(self.engine.away_seconds, 9900.0)  # 7200 + 2700
        self.assertEqual(self.engine.locked_seconds, 0.0)   # NOTHING leaked to locked!

        # User unlocks screen (transition to ACTIVE with 30s delta)
        now += 30.0
        with patch.object(sm_module.time, "time", return_value=now):
            self.engine.transition(ScreenState.ACTIVE)

        self.assertFalse(self.engine._is_lock_escalated_to_away)
        self.assertEqual(self.engine.pending_locked_seconds, 0.0)
        self.assertEqual(self.engine.away_seconds, 9930.0)  # 9900 + 30s
        self.assertEqual(self.engine.locked_seconds, 0.0)   # 0s locked!

    def test_short_lock_session_under_2h_accrues_to_locked(self):
        """Short lock sessions (<2h) must still properly count as LOCKED on unlock."""
        now = 1700000000.0
        with patch.object(sm_module.time, "time", return_value=now):
            self.engine.last_timestamp = now
            self.engine.transition(ScreenState.LOCKED)

        # 45 minutes locked (2700s)
        now += 2700.0
        with patch.object(sm_module.time, "time", return_value=now):
            self.engine.tick()

        self.assertFalse(self.engine._is_lock_escalated_to_away)
        self.assertEqual(self.engine.pending_locked_seconds, 2700.0)
        self.assertEqual(self.engine.away_seconds, 0.0)

        # Unlock screen
        now += 10.0
        with patch.object(sm_module.time, "time", return_value=now):
            self.engine.transition(ScreenState.ACTIVE)

        self.assertEqual(self.engine.pending_locked_seconds, 0.0)
        self.assertEqual(self.engine.locked_seconds, 2710.0)
        self.assertEqual(self.engine.away_seconds, 0.0)
        self.assertFalse(self.engine._is_lock_escalated_to_away)

    def test_lock_escalation_flag_persists_and_restores(self):
        """_is_lock_escalated_to_away must survive persistence and load."""
        self.engine.current_state = ScreenState.LOCKED
        self.engine._is_lock_escalated_to_away = True
        self.engine._persist()

        # Create new engine instance and load persisted state
        new_engine = ScreenTimeEngine(data_dir=self.tmp_dir, agent_id="test-agent")
        loaded = new_engine.load_persisted_state()
        self.assertIsNotNone(loaded)
        new_engine.current_state = ScreenState.LOCKED
        new_engine.load_persisted_state()
        self.assertTrue(new_engine._is_lock_escalated_to_away)


if __name__ == '__main__':
    unittest.main()
