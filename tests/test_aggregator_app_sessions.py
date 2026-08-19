"""
Regression tests for agent/core/aggregator.py::_merge_app_sessions.

Bug: app-usage sessions were reconstructed purely from consecutive
heartbeat (timestamp, app.current) pairs with no gap detection and no
duration cap. If the same app was foreground immediately before and after
a sleep/suspend/crash/offline-backlog gap, the entire gap silently became
one continuous "active app" session with nothing to catch it (unlike
agent/helper/window.py and agent/helper/domain.py, which both cap at 24h).
"""

import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "monitoring_tool", "agent")
)

from core.aggregator import HeartbeatAggregator, MAX_HEARTBEAT_GAP_SECONDS


def _hb(ts: str, app_name, username="alice", title="Title"):
    return {
        "data": {
            "agent_id": "agent-1",
            "username": username,
            "timestamp": ts,
            "app": {"current": app_name, "current_title": title},
        }
    }


class TestAggregatorAppSessionGaps(unittest.TestCase):
    def setUp(self):
        self.buffer = MagicMock()
        self.aggregator = HeartbeatAggregator(buffer=self.buffer)

    def _stored_events(self):
        return [call.args[0] for call in self.buffer.store_merged_event.call_args_list]

    def test_sleep_gap_splits_session_instead_of_merging_it(self):
        # Same app before and after an ~8h gap (e.g. laptop slept overnight
        # with no lock heartbeat in between) must NOT be reported as one
        # continuous ~8h session.
        heartbeats = [
            _hb("2026-01-01T10:00:00+00:00", "chrome.exe"),
            _hb("2026-01-01T10:00:30+00:00", "chrome.exe"),
            _hb("2026-01-01T18:00:00+00:00", "chrome.exe"),  # ~8h later
            _hb("2026-01-01T18:00:30+00:00", "chrome.exe"),
        ]

        self.aggregator._merge_app_sessions("agent-1", heartbeats)

        events = self._stored_events()
        self.assertEqual(len(events), 2, f"expected 2 split sessions, got: {events}")
        for event in events:
            self.assertLessEqual(
                event["duration_seconds"], 31,
                f"session should be ~30s, not span the gap: {event}",
            )
        total_reported = sum(e["duration_seconds"] for e in events)
        self.assertLess(total_reported, 100, "gap must not be folded into reported duration")

    def test_gap_closes_at_last_seen_heartbeat_not_after_the_gap(self):
        heartbeats = [
            _hb("2026-01-01T10:00:00+00:00", "chrome.exe"),
            _hb("2026-01-01T10:00:30+00:00", "chrome.exe"),
            _hb("2026-01-01T18:00:00+00:00", "chrome.exe"),
            _hb("2026-01-01T18:00:30+00:00", "chrome.exe"),
        ]

        self.aggregator._merge_app_sessions("agent-1", heartbeats)

        first_event = self._stored_events()[0]
        self.assertEqual(first_event["end"], "2026-01-01T10:00:30+00:00")

    def test_normal_heartbeat_cadence_does_not_false_split(self):
        # 120s apart (the slowest normal heartbeat interval, used while
        # locked) must stay well under MAX_HEARTBEAT_GAP_SECONDS and not
        # cause spurious splits.
        self.assertGreater(MAX_HEARTBEAT_GAP_SECONDS, 120)
        heartbeats = [
            _hb("2026-01-01T10:00:00+00:00", "chrome.exe"),
            _hb("2026-01-01T10:02:00+00:00", "chrome.exe"),
            _hb("2026-01-01T10:04:00+00:00", "chrome.exe"),
            _hb("2026-01-01T10:06:00+00:00", "chrome.exe"),
        ]

        self.aggregator._merge_app_sessions("agent-1", heartbeats)

        events = self._stored_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["duration_seconds"], 360.0)

    def test_idle_heartbeat_still_closes_session_as_before(self):
        heartbeats = [
            _hb("2026-01-01T10:00:00+00:00", "chrome.exe"),
            _hb("2026-01-01T10:00:30+00:00", None),  # user went idle/locked
            _hb("2026-01-01T10:01:00+00:00", "chrome.exe"),
        ]

        self.aggregator._merge_app_sessions("agent-1", heartbeats)

        events = self._stored_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["duration_seconds"], 30.0)

    def test_store_app_event_caps_at_24_hours(self):
        from datetime import datetime, timezone

        start = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 1, 3, 0, 0, 0, tzinfo=timezone.utc)  # 48h later

        self.aggregator._store_app_event(
            "agent-1", "alice", "chrome.exe", "Title", start, end
        )

        events = self._stored_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["duration_seconds"], 86400)
        self.assertEqual(events[0]["end"], "2026-01-02T00:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
