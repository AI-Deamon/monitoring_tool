"""
Regression tests for StateDetector interrupted-session span recovery.

The helper must not fabricate an overnight active span after a shutdown.
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "monitoring_tool", "agent")
)

from helper.state_detector import StateDetector


class TestStateDetectorRecovery(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.detector = StateDetector.__new__(StateDetector)
        self.detector.state_file = self.tmp_dir / "current_state.json"
        self.detector.pending_spans = []
        self.detector._state_lock = threading.Lock()
        self.detector._transition_lock = threading.RLock()
        self.detector.agent_id = "test-agent"

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

    def test_shutdown_gap_does_not_create_active_recovery_span(self):
        now = 1_800_000_000.0
        self._write_state(session_start=now - (15 * 3600))

        with patch("helper.state_detector.time.time", return_value=now):
            self.detector._load_persisted_state({"last_event": "shutdown"})

        self.assertEqual(self.detector.pending_spans, [])

    def test_long_interrupted_session_is_skipped_not_capped_to_eight_hours(self):
        now = 1_800_000_000.0
        self._write_state(session_start=now - (9 * 3600))

        with patch("helper.state_detector.time.time", return_value=now):
            self.detector._load_persisted_state({"last_event": "normal"})

        self.assertEqual(self.detector.pending_spans, [])

    def test_short_same_day_normal_session_can_recover(self):
        now = 1_800_000_000.0
        self._write_state(session_start=now - 300)

        with patch("helper.state_detector.time.time", return_value=now):
            self.detector._load_persisted_state({"last_event": "normal"})

        self.assertEqual(len(self.detector.pending_spans), 1)
        span = self.detector.pending_spans[0]
        self.assertEqual(span["state"], "active")
        self.assertEqual(span["duration_seconds"], 300)


if __name__ == "__main__":
    unittest.main()
