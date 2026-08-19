"""
Regression tests for a "stuck LOCKED" bug: a transient desktop-inaccessible
blip that is NOT a real OS lock (e.g. a UAC elevation prompt switching to
the secure desktop) must not get stuck forever, because StateAuthority only
allowed LOCKED -> ACTIVE via source="os" and Windows never sends a matching
WTS_SESSION_UNLOCK event for something that was never a real lock.

Fix: a LOCKED state entered via a non-OS heuristic (desktop/process) may
self-correct back to ACTIVE once the same heuristics have reported
"not locked" for HEURISTIC_UNLOCK_CONFIRM_TICKS consecutive polls. A LOCKED
state confirmed by a real OS event (lock_source == "os") remains fully
terminal and never self-corrects.
"""

import os
import sys
import threading
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "monitoring_tool", "agent")
)

from helper.state_detector import (
    StateDetector,
    StateAuthority,
    HEURISTIC_UNLOCK_CONFIRM_TICKS,
)


class TestStateDetectorStuckLock(unittest.TestCase):
    def setUp(self):
        # These tests assert real-WTS-event lock/unlock semantics, which only
        # apply when pywin32 is actually available. Without it, _update_state()
        # intentionally treats any not-locked poll as an OS unlock (its only
        # way to ever detect an unlock at all) — pin HAS_WIN32 so the tests
        # exercise the WTS-event path they're named after regardless of
        # whether pywin32 is installed on the machine running them (e.g. CI).
        self.enterContext(patch("helper.state_detector.HAS_WIN32", True))
        self.detector = StateDetector.__new__(StateDetector)
        self.detector.authority = StateAuthority()
        self.detector._transition_lock = threading.RLock()
        self.detector._state_lock = threading.Lock()
        self.detector.agent_id = "test-agent"
        self.detector.current_state = "active"
        self.detector._last_state_change_time = 1000.0
        self.detector._suspended = False
        self.detector._last_wts_unlock_time = 0
        self.detector._last_unlock_transition_time = 0
        self.detector._heuristic_unlock_streak = 0
        self.detector._foreground_app = None
        self.detector._foreground_app_sample_time = 0
        self.detector.idle_detector = None
        self.detector.collector = None
        self.detector.on_state_change = None
        self.detector.pending_spans = []
        self.detector._final_totals_for_upload = None
        self.detector._final_totals_day_for_upload = None
        self.detector.state_file = MagicMock()
        self.detector.state_file.parent = MagicMock()
        self.detector._buffer_db = MagicMock()
        self.detector._buffer_db_lock = threading.Lock()

        self.detector.screen_time_engine = MagicMock()
        self.detector.screen_time_engine.check_daily_boundary.return_value = (False, None)

    def _tick(self, t, locked):
        with patch("helper.state_detector.time.time", return_value=t), \
             patch.object(self.detector, "_is_session_locked", return_value=locked), \
             patch.object(self.detector, "_persist_current_state"):
            self.detector._update_state()

    def test_false_positive_desktop_lock_self_corrects_after_confirmation_window(self):
        # Tick 1: transient desktop-inaccessible blip (e.g. UAC prompt) is
        # detected by the polling heuristic — NOT a real WTS lock, so no OS
        # lock event accompanies it.
        self._tick(1010.0, locked=True)
        self.assertEqual(self.detector.current_state, "locked")
        self.assertEqual(self.detector.authority.lock_source, "desktop")

        # The prompt is dismissed and the real desktop is accessible again.
        # It takes HEURISTIC_UNLOCK_CONFIRM_TICKS consecutive not-locked
        # polls (10s apart here, well past the 10s unlock grace window) to
        # self-correct — a single blip should not be enough.
        t = 1010.0
        for i in range(HEURISTIC_UNLOCK_CONFIRM_TICKS - 1):
            t += 10.0
            self._tick(t, locked=False)
            self.assertEqual(
                self.detector.current_state,
                "locked",
                f"should not exit LOCKED before the confirmation window (poll {i + 1})",
            )

        t += 10.0
        self._tick(t, locked=False)
        self.assertEqual(self.detector.current_state, "active")

    def test_flicker_during_confirmation_window_resets_the_streak(self):
        self._tick(1010.0, locked=True)
        self.assertEqual(self.detector.current_state, "locked")

        # One not-locked poll, then the heuristic flickers back to "locked"
        # (e.g. a second, brief desktop switch) before confirmation completes.
        self._tick(1020.0, locked=False)
        self._tick(1030.0, locked=True)
        self.assertEqual(self.detector.current_state, "locked")
        self.assertEqual(self.detector._heuristic_unlock_streak, 0)

        # Now confirm cleanly from a reset streak.
        t = 1030.0
        for _ in range(HEURISTIC_UNLOCK_CONFIRM_TICKS):
            t += 10.0
            self._tick(t, locked=False)

        self.assertEqual(self.detector.current_state, "active")

    def test_real_os_lock_never_self_corrects(self):
        # A genuine OS lock event — the authoritative path, unaffected by
        # this fix.
        with patch("helper.state_detector.time.time", return_value=1010.0), \
             patch.object(self.detector, "_persist_current_state"):
            self.detector._transition("locked", source="os")

        self.assertEqual(self.detector.current_state, "locked")
        self.assertEqual(self.detector.authority.lock_source, "os")

        # Even many consecutive "not locked"-looking polls must never
        # release a real OS-confirmed lock — only a real OS unlock event
        # (or resume reconciliation) may do that.
        t = 1010.0
        for _ in range(HEURISTIC_UNLOCK_CONFIRM_TICKS * 5):
            t += 10.0
            self._tick(t, locked=False)
            self.assertEqual(self.detector.current_state, "locked")

    def test_os_lock_event_arriving_after_heuristic_lock_upgrades_lock_source(self):
        # Heuristic (desktop) detects the lock first — e.g. the WTS event
        # hasn't been pumped yet.
        self._tick(1010.0, locked=True)
        self.assertEqual(self.detector.authority.lock_source, "desktop")

        # The real WTS_SESSION_LOCK event arrives a moment later, confirming
        # this was a genuine lock. It must upgrade lock_source to "os" so
        # the lock becomes fully terminal, even though current_state is
        # already "locked" (no visible transition).
        with patch("helper.state_detector.time.time", return_value=1011.0), \
             patch.object(self.detector, "_persist_current_state"):
            self.detector._transition("locked", source="os")

        self.assertEqual(self.detector.authority.lock_source, "os")

        # It must now behave like test_real_os_lock_never_self_corrects:
        # not-locked-looking polls must not release it.
        t = 1011.0
        for _ in range(HEURISTIC_UNLOCK_CONFIRM_TICKS * 3):
            t += 10.0
            self._tick(t, locked=False)
            self.assertEqual(self.detector.current_state, "locked")


if __name__ == "__main__":
    unittest.main()
