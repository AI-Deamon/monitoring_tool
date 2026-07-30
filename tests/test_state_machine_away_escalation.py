"""
Regression test for agent/core/state_machine.py's ScreenTimeEngine.

Bug: when a locked session crosses the 2-hour "count as away instead of
locked" threshold via tick() (the path that fires on wake-from-sleep),
_add_to_current_bucket() added the elapsed gap to away_seconds, then
called self.transition(ScreenState.AWAY), which independently
re-derived and re-added the SAME elapsed gap a second time (because
self.last_timestamp hadn't been advanced yet at that point) - doubling
away_seconds for the whole gap.
"""

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "monitoring_tool", "agent")
)

from core.state_machine import ScreenTimeEngine, ScreenState


class TestAwayEscalationDoesNotDoubleCount(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.engine = ScreenTimeEngine(data_dir=self.tmp_dir, agent_id="test-agent")

    def test_tick_across_locked_sleep_gap_adds_gap_exactly_once(self):
        gap_seconds = 30000.0  # ~8h20m locked+asleep, e.g. overnight
        self.engine.current_state = ScreenState.LOCKED
        self.engine.last_timestamp = time.time() - gap_seconds
        self.engine.pending_locked_seconds = 0.0

        self.engine.tick()

        self.assertAlmostEqual(self.engine.away_seconds, gap_seconds, delta=1.0)
        self.assertEqual(self.engine.pending_locked_seconds, 0.0)

    def test_state_stays_locked_after_escalation_not_away(self):
        gap_seconds = 30000.0
        self.engine.current_state = ScreenState.LOCKED
        self.engine.last_timestamp = time.time() - gap_seconds
        self.engine.pending_locked_seconds = 0.0

        self.engine.tick()

        self.assertEqual(self.engine.current_state, ScreenState.LOCKED)

    def test_locked_session_under_2h_is_unaffected(self):
        gap_seconds = 3600.0  # 1h - under the 7200s threshold
        self.engine.current_state = ScreenState.LOCKED
        self.engine.last_timestamp = time.time() - gap_seconds
        self.engine.pending_locked_seconds = 0.0

        self.engine.tick()

        self.assertAlmostEqual(self.engine.pending_locked_seconds, gap_seconds, delta=1.0)
        self.assertEqual(self.engine.away_seconds, 0.0)


if __name__ == "__main__":
    unittest.main()
