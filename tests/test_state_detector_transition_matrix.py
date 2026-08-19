"""
StateDetector transition matrix tests.

These tests verify branch precedence in _update_state so regressions can be
triaged quickly:
- unlock grace period vs both lock layers
- lock-process (Layer 1, freshness-gated) vs desktop lock (Layer 2) vs idle
- locked terminal behavior (WTS event vs polling fallback)

Matches the current architecture (multi-layer lock detection, 029367d):
the old desktop-lock-conflict tick suppression no longer exists — a positive
desktop lock check always wins outside the unlock grace window.
"""

import os
import sys
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agent'))

from helper import state_detector as sd_module
from helper.state_detector import StateDetector, SystemState


class TestStateDetectorTransitionMatrix(unittest.TestCase):
    def _make_detector(self):
        detector = StateDetector.__new__(StateDetector)
        detector._transition_lock = threading.RLock()
        detector._suspended = False
        detector._last_wts_unlock_time = 0.0
        detector._last_unlock_transition_time = 0.0
        detector._foreground_app = None
        detector._foreground_app_sample_time = 0.0
        detector.current_state = "active"
        detector.authority = MagicMock()
        detector.authority.state = SystemState.ACTIVE
        detector._check_daily_boundary = MagicMock()
        detector._is_session_locked = MagicMock(return_value=False)
        detector._get_idle_seconds = MagicMock(return_value=0.0)
        detector._transition = MagicMock()
        detector.idle_detector = MagicMock()
        detector.idle_detector.is_idle.return_value = False
        return detector

    # ── Lock layer precedence ───────────────────────────────────────────

    def test_desktop_lock_preempts_idle_path(self):
        detector = self._make_detector()
        detector._is_session_locked.return_value = True

        detector._update_state()

        detector._transition.assert_called_once_with("locked", source="desktop")
        detector.idle_detector.update.assert_not_called()

    def test_fresh_lock_process_preempts_desktop_and_idle(self):
        detector = self._make_detector()
        detector._foreground_app = "lockapp.exe"
        detector._foreground_app_sample_time = time.time()
        detector._is_session_locked.return_value = True

        detector._update_state()

        detector._transition.assert_called_once_with("locked", source="process")
        detector.idle_detector.update.assert_not_called()

    def test_stale_lock_process_sample_is_ignored(self):
        # Layer 1 only trusts collector-fed foreground data while fresh
        # (<= 15s old); a stale lockapp sample must not force a lock.
        detector = self._make_detector()
        detector._foreground_app = "lockapp.exe"
        detector._foreground_app_sample_time = 0.0  # never sampled / stale
        detector._is_session_locked.return_value = False
        detector.idle_detector.is_idle.return_value = True

        detector._update_state()

        detector.idle_detector.update.assert_called_once()
        detector._transition.assert_called_once_with("idle", source="idle")

    def test_desktop_lock_wins_over_normal_foreground_app(self):
        # The old conflict-tick suppression is gone: a positive desktop lock
        # check locks even while a normal app is in the foreground.
        detector = self._make_detector()
        detector._foreground_app = "excel.exe"
        detector._foreground_app_sample_time = time.time()
        detector._is_session_locked.return_value = True

        detector._update_state()

        detector._transition.assert_called_once_with("locked", source="desktop")

    # ── Unlock grace period ─────────────────────────────────────────────

    def test_unlock_grace_skips_both_lock_layers(self):
        detector = self._make_detector()
        detector._foreground_app = "lockapp.exe"
        detector._last_unlock_transition_time = 100.0
        detector._is_session_locked.return_value = True

        with patch("helper.state_detector.time.time", return_value=105.0):
            detector._foreground_app_sample_time = 104.0  # fresh sample
            detector._update_state()

        detector.idle_detector.update.assert_called_once()
        detector._transition.assert_called_once_with("active", source="idle")

    def test_wts_unlock_grace_also_blocks_desktop_lock(self):
        detector = self._make_detector()
        detector._last_wts_unlock_time = 100.0
        detector._is_session_locked.return_value = True

        with patch("helper.state_detector.time.time", return_value=105.0):
            detector._update_state()

        detector._transition.assert_called_once_with("active", source="idle")

    def test_expired_unlock_grace_allows_desktop_lock(self):
        detector = self._make_detector()
        detector._last_unlock_transition_time = 100.0
        detector._is_session_locked.return_value = True

        with patch("helper.state_detector.time.time", return_value=111.0):
            detector._update_state()

        detector._transition.assert_called_once_with("locked", source="desktop")

    # ── Locked terminal behavior ────────────────────────────────────────

    def test_locked_waits_for_wts_unlock_when_win32_available(self):
        detector = self._make_detector()
        detector.authority.state = SystemState.LOCKED
        detector._is_session_locked.return_value = False

        with patch.object(sd_module, "HAS_WIN32", True):
            detector._update_state()

        detector._transition.assert_not_called()
        detector.idle_detector.update.assert_not_called()

    def test_locked_polling_unlock_fallback_without_win32(self):
        detector = self._make_detector()
        detector.authority.state = SystemState.LOCKED
        detector._is_session_locked.return_value = False

        with patch.object(sd_module, "HAS_WIN32", False):
            detector._update_state()

        detector._transition.assert_called_once_with("active", source="os")
        detector.idle_detector.update.assert_not_called()

    def test_locked_stays_locked_while_lockapp_foreground(self):
        detector = self._make_detector()
        detector.authority.state = SystemState.LOCKED
        detector._foreground_app = "lockapp.exe"
        detector._foreground_app_sample_time = time.time()
        detector._is_session_locked.return_value = False

        with patch.object(sd_module, "HAS_WIN32", True):
            detector._update_state()

        # Fresh lockapp foreground re-asserts locked; detector is already
        # locked so no new transition and no idle processing.
        detector.idle_detector.update.assert_not_called()
        for call in detector._transition.call_args_list:
            self.assertEqual(call.args[0], "locked")

    # ── Idle path ───────────────────────────────────────────────────────

    def test_no_lock_runs_idle_active_path(self):
        detector = self._make_detector()
        detector._is_session_locked.return_value = False
        detector.idle_detector.is_idle.return_value = False

        detector._update_state()

        detector.idle_detector.update.assert_called_once()
        detector._transition.assert_called_once_with("active", source="idle")

    def test_idle_detector_idle_transitions_to_idle(self):
        detector = self._make_detector()
        detector.idle_detector.is_idle.return_value = True

        detector._update_state()

        detector._transition.assert_called_once_with("idle", source="idle")

    def test_suspended_detector_does_nothing(self):
        detector = self._make_detector()
        detector._suspended = True
        detector._is_session_locked.return_value = True

        detector._update_state()

        detector._transition.assert_not_called()
        detector.idle_detector.update.assert_not_called()


if __name__ == "__main__":
    unittest.main()
