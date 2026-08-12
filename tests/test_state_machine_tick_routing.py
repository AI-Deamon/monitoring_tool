"""
Unit tests for the input-recentcy tick guard (US1, FR-001..FR-003):

When the engine is in ACTIVE state but the injected `user_active_fn`
predicate reports the user unattended, tick() MUST credit the elapsed
delta to IDLE instead of ACTIVE — WITHOUT mutating `current_state`.

Predicate semantics:
- `user_active_fn` is None      -> legacy behavior (always credit current state)
- `user_active_fn()` is True    -> credit current state (ACTIVE)
- `user_active_fn()` is False   -> route delta to IDLE, state unchanged
"""

import time
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime
from unittest.mock import patch
import tempfile
import shutil
import unittest

# Adjust import path for test context
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agent'))

from core import state_machine as sm_module
from core.state_machine import ScreenTimeEngine, ScreenState


class TestTickPredicateRouting(unittest.TestCase):
    """US1: tick() must stop crediting ACTIVE when the user is unattended."""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.engine = ScreenTimeEngine(data_dir=self.tmp_dir, agent_id="test-agent")

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_predicate_false_credits_idle_not_active(self):
        """Predicate False while ACTIVE -> delta lands in idle_seconds."""
        self.engine.current_state = ScreenState.ACTIVE
        self.engine.last_timestamp = time.time() - 30
        self.engine.user_active_fn = lambda: False

        self.engine.tick()

        self.assertAlmostEqual(self.engine.idle_seconds, 30, delta=2)
        self.assertEqual(self.engine.active_seconds, 0.0)
        self.assertAlmostEqual(self.engine.last_timestamp, time.time(), delta=5)

    def test_predicate_false_does_not_mutate_current_state(self):
        """current_state must stay ACTIVE after a routed tick."""
        self.engine.current_state = ScreenState.ACTIVE
        self.engine.last_timestamp = time.time() - 10
        self.engine.user_active_fn = lambda: False

        self.engine.tick()

        self.assertEqual(self.engine.current_state, ScreenState.ACTIVE)

    def test_predicate_true_credits_active(self):
        """Predicate True while ACTIVE -> normal ACTIVE accrual."""
        self.engine.current_state = ScreenState.ACTIVE
        self.engine.last_timestamp = time.time() - 30
        self.engine.user_active_fn = lambda: True

        self.engine.tick()

        self.assertAlmostEqual(self.engine.active_seconds, 30, delta=2)
        self.assertEqual(self.engine.idle_seconds, 0.0)

    def test_predicate_none_default_active_accrual(self):
        """No predicate (None) -> legacy behavior: credit ACTIVE."""
        self.engine.current_state = ScreenState.ACTIVE
        self.engine.last_timestamp = time.time() - 30
        self.engine.user_active_fn = None

        self.engine.tick()

        self.assertAlmostEqual(self.engine.active_seconds, 30, delta=2)
        self.assertEqual(self.engine.idle_seconds, 0.0)

    def test_predicate_false_does_not_affect_idle_state(self):
        """Predicate only reroutes ACTIVE; IDLE accrual is unchanged."""
        self.engine.current_state = ScreenState.IDLE
        self.engine.last_timestamp = time.time() - 30
        self.engine.user_active_fn = lambda: False

        self.engine.tick()

        self.assertAlmostEqual(self.engine.idle_seconds, 30, delta=2)
        self.assertEqual(self.engine.active_seconds, 0.0)


class TestTickMidnightSplitPredicate(unittest.TestCase):
    """US1: with a predicate that reports unattended, BOTH midnight-split
    segments are credited to IDLE (FR-003)."""

    # Frozen 2026-07-11 00:30 IST; the previous tick was 2026-07-10 23:50 IST,
    # so the delta (40min) splits at IST midnight into 10min + 30min.
    FROZEN_NOW = datetime(2026, 7, 11, 0, 30, 0, tzinfo=sm_module._local_tz())
    PREVIOUS_TICK_TS = (
        datetime(2026, 7, 10, 23, 50, 0, tzinfo=sm_module._local_tz()).timestamp()
    )

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.engine = ScreenTimeEngine(data_dir=self.tmp_dir, agent_id="test-agent")

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    @contextmanager
    def frozen_clock(self):
        with patch.object(sm_module.time, "time", return_value=self.FROZEN_NOW.timestamp()), \
                patch.object(sm_module, "_now_ist", return_value=self.FROZEN_NOW):
            yield

    def test_predicate_false_routes_both_segments_to_idle(self):
        """Predicate False -> pre-midnight AND post-midnight deltas -> IDLE."""
        self.engine.current_state = ScreenState.ACTIVE
        self.engine.last_timestamp = self.PREVIOUS_TICK_TS
        self.engine.user_active_fn = lambda: False

        with self.frozen_clock():
            self.engine.tick()

        # 600s (23:50 -> 00:00) + 1800s (00:00 -> 00:30) all routed to IDLE
        self.assertAlmostEqual(self.engine.idle_seconds, 2400, delta=2)
        self.assertEqual(self.engine.active_seconds, 0.0)
        self.assertEqual(self.engine.current_state, ScreenState.ACTIVE)


if __name__ == "__main__":
    unittest.main()
