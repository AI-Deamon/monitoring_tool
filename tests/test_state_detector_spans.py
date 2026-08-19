"""
Unit tests for span reclassification + UTC-midnight splitting (US2, FR-005/FR-012).

- FR-005: a `locked` span whose ORIGINAL duration is >= 2h is recorded as
  `away`; shorter locks stay `locked`; other states are untouched.
- FR-012: a continuous state spanning multiple UTC days is split at UTC
  midnight into one span per UTC day; each segment lands in its own
  `start_time::DATE` bucket; total duration is preserved.
- The `away` decision is computed ONCE from the original duration and applied
  to every segment (a 2.5h lock crossing midnight yields two `away` spans).
"""

import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "monitoring_tool", "agent")
)

from helper.state_detector import StateDetector


def _ts(year, month, day, hour=0, minute=0, second=0):
    return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc).timestamp()


class TestSpanReclassification(unittest.TestCase):
    """FR-005: locked >= 2h -> away; < 2h stays locked; others unchanged."""

    def setUp(self):
        self.detector = StateDetector.__new__(StateDetector)
        self.detector.agent_id = "test-agent"

    def _span(self, state, start_ts, end_ts, duration):
        return self.detector._create_span(
            state=state, start_time=start_ts, end_time=end_ts, duration=duration
        )

    def test_locked_2_5h_reclassifies_to_away(self):
        start = _ts(2026, 7, 17, 10, 0, 0)
        span = self._span("locked", start, start + 9000, 9000)
        self.assertIsNotNone(span)
        self.assertEqual(span["state"], "away")
        self.assertEqual(span["duration_seconds"], 9000)

    def test_locked_30min_stays_locked(self):
        start = _ts(2026, 7, 17, 10, 0, 0)
        span = self._span("locked", start, start + 1800, 1800)
        self.assertIsNotNone(span)
        self.assertEqual(span["state"], "locked")
        self.assertEqual(span["duration_seconds"], 1800)

    def test_idle_span_unaffected(self):
        start = _ts(2026, 7, 17, 10, 0, 0)
        span = self._span("idle", start, start + 9000, 9000)
        self.assertIsNotNone(span)
        self.assertEqual(span["state"], "idle")

    def test_active_span_unaffected(self):
        start = _ts(2026, 7, 17, 10, 0, 0)
        span = self._span("active", start, start + 9000, 9000)
        self.assertIsNotNone(span)
        self.assertEqual(span["state"], "active")


class TestUtcMidnightSplitting(unittest.TestCase):
    """FR-012: one span per UTC day, total duration preserved."""

    def setUp(self):
        self.detector = StateDetector.__new__(StateDetector)
        self.detector.agent_id = "test-agent"

    def _segments(self, state, start_ts, end_ts, duration=None):
        return self.detector._create_span_segments(
            state=state, start_time=start_ts, end_time=end_ts, duration=duration
        )

    def test_fri_1800_to_mon_0900_yields_four_daily_spans(self):
        # 2026-07-17 is a Friday, 2026-07-20 is the following Monday.
        start = _ts(2026, 7, 17, 18, 0, 0)
        end = _ts(2026, 7, 20, 9, 0, 0)
        spans = self._segments("locked", start, end)

        self.assertEqual(len(spans), 4)
        # One span per UTC day it touches: Fri, Sat, Sun, Mon.
        self.assertEqual([s["start_time"][:10] for s in spans], [
            "2026-07-17", "2026-07-18", "2026-07-19", "2026-07-20",
        ])
        # Every span fits inside its bucket day: [start, end) may end at the
        # next UTC midnight (half-open day boundary) but never beyond it.
        for s in spans:
            s_day = datetime.fromisoformat(s["start_time"]).date()
            e_day = datetime.fromisoformat(s["end_time"]).date()
            self.assertLessEqual(
                e_day, s_day + timedelta(days=1), f"span crosses a UTC day: {s}"
            )
        # Total duration preserved: 6h + 24h + 24h + 9h = 63h.
        self.assertEqual(sum(s["duration_seconds"] for s in spans), 63 * 3600)
        # A 63h lock is >= 2h, so EVERY segment is reclassified to away.
        self.assertTrue(all(s["state"] == "away" for s in spans))

    def test_single_day_state_stays_single_span(self):
        start = _ts(2026, 7, 17, 10, 0, 0)
        spans = self._segments("active", start, start + 1800)
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0]["state"], "active")
        self.assertEqual(spans[0]["duration_seconds"], 1800)

    def test_boundary_2350_to_0010_yields_two_spans(self):
        # 23:50 -> 00:10 UTC splits at midnight into 10min + 10min.
        start = _ts(2026, 7, 17, 23, 50, 0)
        end = _ts(2026, 7, 18, 0, 10, 0)
        spans = self._segments("active", start, end)

        self.assertEqual(len(spans), 2)
        self.assertEqual([s["start_time"][:10] for s in spans], [
            "2026-07-17", "2026-07-18",
        ])
        self.assertEqual([s["duration_seconds"] for s in spans], [600, 600])

    def test_exact_24h_span_stays_single_span(self):
        # 00:00 -> 00:00 next day: exactly one 86400s span (cap is a no-op).
        start = _ts(2026, 7, 17, 0, 0, 0)
        end = _ts(2026, 7, 18, 0, 0, 0)
        spans = self._segments("idle", start, end)

        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0]["duration_seconds"], 86400)
        self.assertEqual(spans[0]["start_time"][:10], "2026-07-17")

    def test_25h_lock_crossing_midnight_yields_two_away_segments(self):
        # 23:00 -> 01:30 UTC: original duration 2.5h (>= 2h) decides away
        # ONCE; BOTH segments carry state 'away' (FR-005 on original duration).
        start = _ts(2026, 7, 17, 23, 0, 0)
        end = _ts(2026, 7, 18, 1, 30, 0)
        spans = self._segments("locked", start, end)

        self.assertEqual(len(spans), 2)
        self.assertEqual([s["duration_seconds"] for s in spans], [3600, 5400])
        self.assertTrue(all(s["state"] == "away" for s in spans))
        self.assertEqual([s["start_time"][:10] for s in spans], [
            "2026-07-17", "2026-07-18",
        ])

    def test_90min_lock_crossing_midnight_stays_locked(self):
        # 23:30 -> 01:00 UTC: original duration 1.5h (< 2h) -> both locked.
        start = _ts(2026, 7, 17, 23, 30, 0)
        end = _ts(2026, 7, 18, 1, 0, 0)
        spans = self._segments("locked", start, end)

        self.assertEqual(len(spans), 2)
        self.assertTrue(all(s["state"] == "locked" for s in spans))
        self.assertEqual(sum(s["duration_seconds"] for s in spans), 5400)

    def test_segments_have_distinct_span_ids(self):
        start = _ts(2026, 7, 17, 18, 0, 0)
        end = _ts(2026, 7, 20, 9, 0, 0)
        spans = self._segments("locked", start, end)
        ids = [s["span_id"] for s in spans]
        self.assertEqual(len(ids), len(set(ids)), "span_id must be distinct per segment")


if __name__ == "__main__":
    unittest.main()
