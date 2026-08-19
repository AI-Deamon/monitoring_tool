"""
Unit tests for low-level session lock probing behavior.

_is_session_locked() runs TWO probes, and both must be mocked for these tests to
mean anything. Method 1 is the OpenInputDesktop accessibility check. Method 2
reads the foreground window's process name and declares the session locked when
it is lockapp.exe or logonui.exe.

Leaving Method 2 unmocked made these tests depend on whether the developer's own
screen happened to be locked while pytest ran — green at a desk, red after
stepping away, with nothing in the diff to explain it. GetForegroundWindow is
therefore pinned to 0 (no foreground window), which short-circuits Method 2 and
leaves Method 1 as the only thing under test, which is the point.
"""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'monitoring_tool', 'agent'))

from helper.state_detector import StateDetector


class TestStateDetectorSessionLockProbe(unittest.TestCase):
    def test_is_session_locked_does_not_bypass_probe_for_remote_metric(self):
        detector = StateDetector.__new__(StateDetector)

        with patch("helper.state_detector.windll.user32.GetSystemMetrics", return_value=1), \
             patch("helper.state_detector.windll.user32.OpenInputDesktop", return_value=123), \
             patch("helper.state_detector.windll.user32.GetForegroundWindow", return_value=0), \
             patch("helper.state_detector.windll.user32.CloseDesktop") as close_desktop:
            self.assertFalse(detector._is_session_locked())
            close_desktop.assert_called_once_with(123)

    def test_is_session_locked_uses_desktop_probe_for_local_session(self):
        detector = StateDetector.__new__(StateDetector)

        with patch("helper.state_detector.windll.user32.GetSystemMetrics", return_value=0), \
             patch("helper.state_detector.windll.user32.OpenInputDesktop", return_value=123), \
             patch("helper.state_detector.windll.user32.GetForegroundWindow", return_value=0), \
             patch("helper.state_detector.windll.user32.CloseDesktop") as close_desktop:
            self.assertFalse(detector._is_session_locked())
            close_desktop.assert_called_once_with(123)


if __name__ == "__main__":
    unittest.main()
