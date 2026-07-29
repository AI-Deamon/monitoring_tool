"""
Regression test for agent/helper/domain.py::cleanup_orphaned_sessions.

Bug: an orphaned domain session (one left open in persisted state across
a crash/unclean restart) always got reported with a hardcoded
duration_seconds=7200, regardless of how long it had actually been
orphaned (2h05m and 12 days both produced the same 7200). There is no way
to know how long the domain was really being viewed before the crash
interrupted tracking, so fabricating any duration is inventing data.
"""

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "monitoring_tool", "agent")
)

from helper.domain import ActiveDomainTracker, DomainSession


class TestDomainOrphanedSessionCleanup(unittest.TestCase):
    def setUp(self):
        self.tracker = ActiveDomainTracker.__new__(ActiveDomainTracker)
        self.tracker._pending_sessions = []
        self.tracker._tracking_active = True

    def _orphaned_session(self, hours_old: float) -> DomainSession:
        session = DomainSession(domain="example.com", browser="Chrome")
        session.start_time = datetime.now(timezone.utc) - timedelta(hours=hours_old)
        return session

    def test_orphaned_session_is_discarded_not_fabricated(self):
        self.tracker._current_session = self._orphaned_session(hours_old=2.1)

        self.tracker.cleanup_orphaned_sessions()

        self.assertIsNone(self.tracker._current_session)
        self.assertFalse(self.tracker._tracking_active)
        self.assertEqual(
            self.tracker._pending_sessions, [],
            "no fabricated duration should be reported for an orphaned session",
        )

    def test_long_orphaned_session_is_also_discarded_not_fabricated(self):
        self.tracker._current_session = self._orphaned_session(hours_old=12 * 24)

        self.tracker.cleanup_orphaned_sessions()

        self.assertIsNone(self.tracker._current_session)
        self.assertEqual(self.tracker._pending_sessions, [])

    def test_recent_session_is_left_alone(self):
        session = self._orphaned_session(hours_old=0.5)
        self.tracker._current_session = session

        self.tracker.cleanup_orphaned_sessions()

        # Not orphaned yet (under the 2h threshold) - must be left running,
        # not force-ended.
        self.assertIs(self.tracker._current_session, session)
        self.assertEqual(self.tracker._pending_sessions, [])

    def test_no_current_session_is_a_no_op(self):
        self.tracker._current_session = None

        self.tracker.cleanup_orphaned_sessions()  # must not raise

        self.assertIsNone(self.tracker._current_session)
        self.assertEqual(self.tracker._pending_sessions, [])


if __name__ == "__main__":
    unittest.main()
