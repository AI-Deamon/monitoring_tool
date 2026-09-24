"""
Regression tests for StateDetector interrupted-session span recovery and lock preservation.

Covers:
1. Production sequence: LOCKED -> display sleep -> 7h gap -> recovered as AWAY (0 active).
2. ACTIVE persisted state + ignored unknown gap -> 0 recovered active spans.
3. NULL foreground window while LOCKED -> preserves LOCKED.
4. Genuine unlock with user input -> transitions to ACTIVE.
5. Overnight work before lock preserved (01:00->02:57 ACTIVE, 02:57->09:59 AWAY).
6. Cross-midnight active session split by calendar day.
7. Away threshold: 7199s is LOCKED, 7200s is AWAY.
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "monitoring_tool", "agent")
)

from helper.state_detector import (
    StateDetector,
    SystemState,
    StateAuthority,
    HEURISTIC_UNLOCK_CONFIRM_TICKS,
)
from core.state_machine import ScreenTimeEngine


class TestStateDetectorRecovery(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.detector = StateDetector.__new__(StateDetector)
        self.detector.state_file = self.tmp_dir / "current_state.json"
        self.detector.pending_spans = []
        self.detector._state_lock = threading.Lock()
        self.detector._transition_lock = threading.RLock()
        self.detector.agent_id = "test-agent"
        self.detector.authority = StateAuthority()
        self.detector.current_state = "active"
        self.detector.idle_threshold = 120
        self.detector._heuristic_unlock_streak = 0
        self.detector.idle_detector = None
        self.detector._foreground_app_sample_time = 0
        self.detector._foreground_app = None
        self.detector._last_state_change_time = 0.0
        self.detector._final_totals_for_upload = None
        self.detector._final_totals_day_for_upload = None
        self.detector.data_dir = str(self.tmp_dir)
        self.detector._suspended = False
        self.detector._post_unlock_grace_until = 0.0
        self.detector._last_wts_unlock_time = 0.0
        self.detector._last_unlock_transition_time = 0.0
        self.detector.screen_time_engine = MagicMock()
        self.detector.screen_time_engine.check_daily_boundary.return_value = (False, None)
        self.detector.on_state_change = None

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _write_state(self, *, state="active", session_start=0.0, day=None):
        payload = {
            "current_state": state,
            "session_start": session_start,
            "date": day or datetime.now().date().isoformat(),
            "timestamp": session_start,
        }
        self.detector.state_file.write_text(json.dumps(payload), encoding="utf-8")

    # ------------------------------------------------------------------------
    # Baseline tests
    # ------------------------------------------------------------------------

    def test_shutdown_gap_does_not_create_active_recovery_span(self):
        now = 1_800_000_000.0
        self._write_state(state="active", session_start=now - (15 * 3600))

        with patch("helper.state_detector.time.time", return_value=now):
            self.detector._load_persisted_state({"last_event": "shutdown"})

        self.assertEqual(self.detector.pending_spans, [])

    def test_long_interrupted_session_is_skipped_not_capped_to_eight_hours(self):
        now = 1_800_000_000.0
        self._write_state(state="active", session_start=now - (9 * 3600))

        with patch("helper.state_detector.time.time", return_value=now):
            self.detector._load_persisted_state({"last_event": "normal"})

        self.assertEqual(self.detector.pending_spans, [])

    def test_short_same_day_normal_session_can_recover(self):
        now = 1_800_000_000.0
        self._write_state(state="active", session_start=now - 300)

        with patch("helper.state_detector.time.time", return_value=now):
            self.detector._load_persisted_state({"last_event": "normal"})

        self.assertEqual(len(self.detector.pending_spans), 1)
        span = self.detector.pending_spans[0]
        self.assertEqual(span["state"], "active")
        self.assertEqual(span["duration_seconds"], 300)

    def test_persisted_state_recovered_when_win32_not_available(self):
        """Ensure load_persisted_state runs even when HAS_WIN32 is False."""
        data_dir = self.tmp_dir
        with patch("helper.state_detector.HAS_WIN32", False), \
             patch("helper.state_detector.ScreenTimeEngine") as mock_engine_cls:
            mock_engine = mock_engine_cls.return_value
            mock_engine.load_persisted_state.return_value = {"last_event": "normal"}
            mock_engine.handle_startup.return_value = {"action": "ok"}

            detector = StateDetector(data_dir=data_dir, agent_id="test")

            mock_engine.load_persisted_state.assert_called_once()
            mock_engine.handle_startup.assert_called_once()

    # ------------------------------------------------------------------------
    # Required Regression Tests 1 - 7
    # ------------------------------------------------------------------------

    def test_1_production_sequence_overnight_lock_to_away(self):
        """
        Test 1 — Production sequence:
        LOCKED at 02:57 -> display sleep -> 7-hour overnight gap (25,186s) -> restart.
        Expected:
        - No fabricated ACTIVE time (recovered active seconds == 0).
        - Overnight qualifying period is recovered as AWAY span(s).
        """
        now = 1_800_000_000.0
        gap_seconds = 25186.5
        lock_start = now - gap_seconds

        self._write_state(state="locked", session_start=lock_start)

        gap_info = {
            "action": "counted_as_away",
            "gap_seconds": gap_seconds,
            "gap_hours": gap_seconds / 3600,
        }
        with patch("helper.state_detector.time.time", return_value=now):
            self.detector._load_persisted_state(
                state_machine_state={"last_event": "normal"},
                gap_info=gap_info,
            )

        self.assertGreaterEqual(len(self.detector.pending_spans), 1)
        for span in self.detector.pending_spans:
            self.assertEqual(
                span["state"],
                "away",
                "Overnight locked span >= 2h must be resolved to AWAY",
            )
            self.assertNotEqual(
                span["state"], "active", "Must NOT synthesize active time overnight"
            )

        total_recovered = sum(
            s["duration_seconds"] for s in self.detector.pending_spans
        )
        self.assertAlmostEqual(total_recovered, int(gap_seconds), delta=2)

    def test_2_active_persisted_state_with_ignored_unknown_gap(self):
        """
        Test 2 — ACTIVE persisted state + ignored unknown gap:
        Input: persisted state = ACTIVE, gap ≈ 7 hours, gap_info.action = ignored_unknown_gap.
        Expected: recovered ACTIVE time == 0, no active span synthesized.
        """
        now = 1_800_000_000.0
        gap_seconds = 25186.5
        session_start = now - gap_seconds

        self._write_state(state="active", session_start=session_start)

        gap_info = {
            "action": "ignored_unknown_gap",
            "gap_seconds": gap_seconds,
            "gap_hours": gap_seconds / 3600,
        }
        with patch("helper.state_detector.time.time", return_value=now):
            self.detector._load_persisted_state(
                state_machine_state={"last_event": "normal"},
                gap_info=gap_info,
            )

        active_spans = [
            s for s in self.detector.pending_spans if s["state"] == "active"
        ]
        self.assertEqual(
            active_spans,
            [],
            "Ignored unknown gap must NEVER synthesize active spans",
        )

    def test_3_null_foreground_while_locked_preserves_locked(self):
        """
        Test 3 — NULL foreground while LOCKED:
        Input: current state = LOCKED, foreground window = NULL, no user input.
        Expected: _is_session_locked returns True, state remains LOCKED.
        """
        self.detector.authority.set_state(SystemState.LOCKED, source="desktop")
        self.detector.current_state = "locked"

        with patch("helper.state_detector.windll") as mock_windll:
            mock_windll.user32.OpenInputDesktop.return_value = 1
            mock_windll.user32.CloseDesktop.return_value = 1
            mock_windll.user32.GetForegroundWindow.return_value = 0  # NULL hwnd

            is_locked = self.detector._is_session_locked()
            self.assertTrue(
                is_locked,
                "NULL foreground window while already LOCKED must preserve LOCKED",
            )

    def test_4_genuine_unlock_activity(self):
        """
        Test 4 — Genuine unlock/activity:
        Input: current state = LOCKED, user genuinely unlocks (not locked), recent keyboard/mouse activity.
        Expected: LOCKED -> ACTIVE transition succeeds.
        """
        self.detector.authority.set_state(SystemState.LOCKED, source="desktop")
        self.detector.current_state = "locked"
        self.detector._get_idle_seconds = lambda: 1.5  # Active user input (< idle_threshold)
        self.detector._is_session_locked = lambda: False  # Screen is unlocked

        for _ in range(HEURISTIC_UNLOCK_CONFIRM_TICKS):
            self.detector._update_state()

        self.assertEqual(
            self.detector.authority.state,
            SystemState.ACTIVE,
            "Genuine user activity must unlock to ACTIVE",
        )
        self.assertEqual(self.detector.current_state, "active")

    def test_5_overnight_work_before_lock_isolated(self):
        """
        Test 5 — Overnight work before lock:
        01:00 -> 02:57 ACTIVE (already closed/sent before lock)
        02:57 -> 09:59 LOCKED
        Expected:
        Only 02:57 -> 09:59 is recovered as AWAY. The prior active span is untouched.
        """
        now = 1_800_000_000.0
        lock_start = now - (7 * 3600)  # 7 hours ago
        active_prior_start = lock_start - (1.95 * 3600)

        # Emulate the prior active span that completed at 02:57
        prior_active_span = self.detector._create_span(
            "active", active_prior_start, lock_start, lock_start - active_prior_start
        )
        self.assertEqual(prior_active_span["state"], "active")
        self.assertEqual(prior_active_span["duration_seconds"], 1.95 * 3600)

        # Now recover the persisted locked session (lock_start -> now)
        self._write_state(state="locked", session_start=lock_start)
        with patch("helper.state_detector.time.time", return_value=now):
            self.detector._load_persisted_state(
                state_machine_state={"last_event": "normal"},
                gap_info={
                    "action": "counted_as_away",
                    "gap_seconds": 7 * 3600,
                    "gap_hours": 7.0,
                },
            )

        self.assertGreaterEqual(len(self.detector.pending_spans), 1)
        for s in self.detector.pending_spans:
            self.assertEqual(s["state"], "away")
            self.assertEqual(s["duration_seconds"], 7 * 3600)

    def test_6_cross_midnight_active_session_splitting(self):
        """
        Test 6 — Cross-midnight active session:
        Session crossing UTC midnight must be split into two spans:
        Segment 1: day 1 up to 23:59:59 UTC
        Segment 2: day 2 starting at 00:00:00 UTC
        """
        start_dt = datetime(2026, 9, 22, 23, 0, 0, tzinfo=timezone.utc)
        end_dt = datetime(2026, 9, 23, 2, 57, 0, tzinfo=timezone.utc)
        start_ts = start_dt.timestamp()
        end_ts = end_dt.timestamp()
        duration = end_ts - start_ts

        spans = self.detector._create_span_segments(
            state="active",
            start_time=start_ts,
            end_time=end_ts,
            duration=duration,
        )

        self.assertEqual(len(spans), 2, "Cross-midnight session must be split into 2 spans")
        self.assertEqual(spans[0]["state"], "active")
        self.assertEqual(spans[1]["state"], "active")
        self.assertEqual(spans[0]["duration_seconds"], 3600)  # 23:00 to 00:00 = 1 hour
        self.assertEqual(
            spans[1]["duration_seconds"], 2 * 3600 + 57 * 60
        )  # 00:00 to 02:57

    def test_7_away_threshold_boundary(self):
        """
        Test 7 — Away threshold:
        Verify:
        7199 seconds -> locked
        7200 seconds -> away (inclusive >= 7200)
        """
        start_ts = 1_800_000_000.0

        span_7199 = self.detector._create_span_segments(
            state="locked",
            start_time=start_ts,
            end_time=start_ts + 7199,
            duration=7199,
        )
        self.assertEqual(len(span_7199), 1)
        self.assertEqual(
            span_7199[0]["state"],
            "locked",
            "7199s is under the 7200s threshold, must remain locked",
        )

        span_7200 = self.detector._create_span_segments(
            state="locked",
            start_time=start_ts,
            end_time=start_ts + 7200,
            duration=7200,
        )
        self.assertEqual(len(span_7200), 1)
        self.assertEqual(
            span_7200[0]["state"],
            "away",
            "7200s satisfies the threshold, must resolve to away",
        )


if __name__ == "__main__":
    unittest.main()
