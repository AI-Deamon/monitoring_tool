"""
Unit tests for low-level session lock probing behavior.
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
             patch("helper.state_detector.windll.user32.CloseDesktop") as close_desktop:
            self.assertFalse(detector._is_session_locked())
            close_desktop.assert_called_once_with(123)

    def test_is_session_locked_uses_desktop_probe_for_local_session(self):
        detector = StateDetector.__new__(StateDetector)

        with patch("helper.state_detector.windll.user32.GetSystemMetrics", return_value=0), \
             patch("helper.state_detector.windll.user32.OpenInputDesktop", return_value=123), \
             patch("helper.state_detector.windll.user32.CloseDesktop") as close_desktop:
            self.assertFalse(detector._is_session_locked())
            close_desktop.assert_called_once_with(123)


if __name__ == "__main__":
    unittest.main()
