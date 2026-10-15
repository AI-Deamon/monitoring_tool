"""
Unit Test Suite for Screen Time Active Gap & Timeline Span Resolution
======================================================================
Tests that:
1. Long active transition deltas are redirected to LOCK/AWAY progression (no active inflation).
2. Continuous active timeline spans >= 7200s resolve to 'away' (no green active bar overnight).
3. Active timeline spans >= 600s and < 7200s resolve to 'locked'.
4. Shutdown gaps remain completely ignored.
"""

import os
import sys
import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure agent directory is in Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "agent")))

from core.state_machine import ScreenTimeEngine, ScreenState, LastEvent


class TestActiveGapScreenTimeEngine(unittest.TestCase):
    """Test ScreenTimeEngine handling of un-monitored active gaps."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)
        self.engine = ScreenTimeEngine(data_dir=self.data_dir, agent_id="test-agent")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_active_gap_under_threshold_credits_active(self):
        """Active tick under 120s credits to active_seconds."""
        self.engine.last_timestamp = time.time() - 30.0
        self.engine.tick()
        self.assertAlmostEqual(self.engine.active_seconds, 30.0, delta=2.0)
        self.assertEqual(self.engine.away_seconds, 0.0)

    def test_overnight_active_gap_redirects_to_away(self):
        """Overnight un-monitored active gap (>= 7200s) redirects 100% to away_seconds."""
        start_ts = time.time() - 14400.0  # 4 hours ago
        self.engine.last_timestamp = start_ts
        self.engine.current_state = ScreenState.ACTIVE

        # Execute tick with 4h gap
        self.engine.tick()

        # Active time must NOT be inflated
        self.assertEqual(self.engine.active_seconds, 0.0)
        # 4h gap must go 100% to away_seconds
        self.assertAlmostEqual(self.engine.away_seconds, 14400.0, delta=5.0)

    def test_shutdown_gap_is_ignored(self):
        """Shutdown gap must be ignored (0 seconds added to any bucket)."""
        persisted = {
            "last_event": "shutdown",
            "last_timestamp": time.time() - 10000.0,
            "current_state": "ACTIVE",
        }
        res = self.engine.handle_startup(persisted)
        self.assertEqual(res["action"], "ignored_shutdown_gap")
        self.assertEqual(self.engine.active_seconds, 0.0)
        self.assertEqual(self.engine.away_seconds, 0.0)
        self.assertEqual(self.engine.locked_seconds, 0.0)

    def test_unmonitored_idle_gap_redirects_to_locked(self):
        """Unmonitored runtime gap during IDLE redirects to locked_seconds."""
        self.engine.current_state = ScreenState.IDLE
        self.engine.last_timestamp = time.time() - 1800.0  # 30m ago
        res = self.engine.transition(ScreenState.ACTIVE)
        self.assertTrue(res["was_unmonitored_gap"])
        self.assertEqual(self.engine.idle_seconds, 0.0)
        self.assertAlmostEqual(self.engine.locked_seconds, 1800.0, delta=5.0)

    def test_startup_unknown_gap_after_active_counts_as_locked(self):
        """Startup unknown gap when previous state was ACTIVE counts as locked (< 2h)."""
        persisted = {
            "last_event": "normal",
            "last_timestamp": time.time() - 1800.0,
            "current_state": "ACTIVE",
        }
        res = self.engine.handle_startup(persisted)
        self.assertEqual(res["action"], "counted_as_locked")
        self.assertEqual(self.engine.active_seconds, 0.0)
        self.assertAlmostEqual(self.engine.locked_seconds, 1800.0, delta=5.0)

    def test_startup_unknown_gap_after_idle_counts_as_away(self):
        """Startup unknown gap when previous state was IDLE counts as away (>= 2h)."""
        persisted = {
            "last_event": "normal",
            "last_timestamp": time.time() - 10000.0,
            "current_state": "IDLE",
        }
        res = self.engine.handle_startup(persisted)
        self.assertEqual(res["action"], "counted_as_away")
        self.assertEqual(self.engine.idle_seconds, 0.0)
        self.assertAlmostEqual(self.engine.away_seconds, 10000.0, delta=5.0)


class TestStateDetectorSpanResolution(unittest.TestCase):
    """Test state_detector._create_span_segments timeline span resolution."""

    def test_active_unmonitored_gap_redirects_span_to_locked(self):
        """Unmonitored active gap < 2h in _transition redirects emitted span to 'locked'."""
        from helper.state_detector import StateDetector
        from core.state_machine import ScreenTimeEngine

        engine = MagicMock(spec=ScreenTimeEngine)
        engine.transition.return_value = {
            "from": "ACTIVE",
            "to": "IDLE",
            "delta_seconds": 1800.0,
            "was_unmonitored_gap": True,
        }

        detector = StateDetector(agent_id="test-agent")
        detector.screen_time_engine = engine
        detector.current_state = "active"
        detector._last_state_change_time = time.time() - 1800.0

        detector._transition("idle", source="idle")

        self.assertTrue(len(detector.pending_spans) >= 1)
        self.assertEqual(detector.pending_spans[-1]["state"], "locked")

    def test_active_unmonitored_gap_over_2h_redirects_span_to_away(self):
        """Unmonitored active gap >= 2h in _transition redirects emitted span to 'away'."""
        from helper.state_detector import StateDetector
        from core.state_machine import ScreenTimeEngine

        engine = MagicMock(spec=ScreenTimeEngine)
        engine.transition.return_value = {
            "from": "ACTIVE",
            "to": "IDLE",
            "delta_seconds": 14400.0,
            "was_unmonitored_gap": True,
        }

        detector = StateDetector(agent_id="test-agent")
        detector.screen_time_engine = engine
        detector.current_state = "active"
        detector._last_state_change_time = time.time() - 14400.0

        detector._transition("idle", source="idle")

        self.assertTrue(len(detector.pending_spans) >= 1)
        self.assertEqual(detector.pending_spans[-1]["state"], "away")


if __name__ == "__main__":
    unittest.main()
