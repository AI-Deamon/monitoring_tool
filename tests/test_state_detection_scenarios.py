"""
Targeted scenario tests for StateDetector suspend/resume and lock precedence.
"""

import threading
import unittest
from unittest.mock import MagicMock, patch
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agent'))

from helper import state_detector as sd_module
from helper.state_detector import StateDetector, SystemState


class TestStateDetectorScenarios(unittest.TestCase):
    def _make_detector(self):
        detector = StateDetector.__new__(StateDetector)
        detector._transition_lock = threading.RLock()
        detector._suspended = False
        detector._suspend_started_at = None
        detector.current_state = "active"
        detector._last_wts_unlock_time = 0.0
        detector._last_unlock_transition_time = 0.0
        detector._foreground_app_sample_time = 0.0
        detector.collector = MagicMock()
        detector.collector.active_domain_tracker = MagicMock()
        detector.screen_time_engine = MagicMock()
        detector.authority = MagicMock()
        detector.authority.state = SystemState.ACTIVE
        detector._persist_current_state = MagicMock()
        detector._transition = MagicMock()
        detector._is_session_locked = MagicMock(return_value=False)
        detector._check_daily_boundary = MagicMock()
        detector._foreground_app = None
        detector.idle_detector = None
        return detector

    def test_suspend_from_active_transitions_to_away(self):
        detector = self._make_detector()
        detector.current_state = "active"

        detector._handle_suspend()

        detector.screen_time_engine.mark_sleep.assert_called_once()
        detector._transition.assert_called_once_with("away", source="os")
        self.assertTrue(detector._suspended)

    def test_suspend_from_locked_keeps_locked(self):
        detector = self._make_detector()
        detector.current_state = "locked"

        detector._handle_suspend()

        detector.screen_time_engine.mark_sleep.assert_called_once()
        detector._transition.assert_not_called()
        self.assertTrue(detector._suspended)

    def test_resume_reconciles_before_mark_resume(self):
        detector = self._make_detector()
        detector._suspended = True
        detector._is_session_locked.return_value = True
        order = []
        detector._transition.side_effect = lambda *args, **kwargs: order.append("transition")
        detector.screen_time_engine.mark_resume.side_effect = lambda: order.append("resume")

        detector._handle_resume()

        self.assertEqual(order, ["transition", "resume"])
        detector._transition.assert_called_once_with("locked", source="os")
        self.assertFalse(detector._suspended)

    def test_locked_state_can_exit_via_polling_unlock_without_win32(self):
        # Polling unlock is now the fallback when WTS events are unavailable;
        # with win32 present the detector waits for the OS unlock event.
        detector = self._make_detector()
        detector.authority.state = SystemState.LOCKED
        detector._is_session_locked.return_value = False

        with patch.object(sd_module, "HAS_WIN32", False):
            detector._update_state()

        detector._transition.assert_called_once_with("active", source="os")

    def test_lock_process_ignored_during_unlock_grace_when_desktop_is_accessible(self):
        detector = self._make_detector()
        detector._foreground_app = "lockapp.exe"
        detector._last_unlock_transition_time = 100.0
        detector._is_session_locked.return_value = False

        with patch("helper.state_detector.time.time", return_value=105.0):
            detector._foreground_app_sample_time = 104.0
            detector._update_state()

        detector._transition.assert_called_once_with("active", source="idle")

    def test_unlock_grace_suppresses_even_desktop_reported_lock(self):
        # Grace now unconditionally skips both lock layers for 10s after an
        # unlock, absorbing transient locked readings during fast unlocks.
        detector = self._make_detector()
        detector._foreground_app = "lockapp.exe"
        detector._last_unlock_transition_time = 100.0
        detector._is_session_locked.return_value = True

        with patch("helper.state_detector.time.time", return_value=105.0):
            detector._foreground_app_sample_time = 104.0
            detector._update_state()

        detector._transition.assert_called_once_with("active", source="idle")

    def test_lock_process_after_unlock_grace_transitions_locked(self):
        detector = self._make_detector()
        detector._foreground_app = "lockapp.exe"
        detector._last_unlock_transition_time = 100.0
        detector._is_session_locked.return_value = False

        with patch("helper.state_detector.time.time", return_value=111.0):
            detector._foreground_app_sample_time = 110.0
            detector._update_state()

        detector._transition.assert_called_once_with("locked", source="process")


if __name__ == "__main__":
    unittest.main()
