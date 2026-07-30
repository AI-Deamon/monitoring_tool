"""
Regression test for server_dashboard.py's IST-day-to-UTC-range conversion.

Bug: api_agent_full_report() computed target_date as an IST calendar date
(get_ist_today()), then built query bounds with a plain, timezone-naive
datetime.combine(target_date, ...) - which does NOT shift by IST's +5:30
offset. Since every stored timestamp is normalized to naive UTC on write
(server_telemetry.parse_agent_timestamp), "today's" query window ended up
being the UTC calendar day sharing the same date number, not the true IST
day - a systematic ~5.5 hour misalignment, every day.
"""

import os
import sys
import unittest
from datetime import date, datetime, timedelta, timezone

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "monitoring_tool", "server")
)

from server_dashboard import get_ist_day_range_utc


class TestIstDayRangeUtc(unittest.TestCase):
    def test_ist_midnight_converts_to_correct_utc_start(self):
        # IST midnight on 2026-07-29 is 18:30 UTC on 2026-07-28.
        start_dt, end_dt = get_ist_day_range_utc(date(2026, 7, 29))

        self.assertEqual(start_dt, datetime(2026, 7, 28, 18, 30, 0))

    def test_range_ends_just_before_next_ist_midnight(self):
        start_dt, end_dt = get_ist_day_range_utc(date(2026, 7, 29))

        # Next IST midnight (2026-07-30 00:00 IST) is 2026-07-29 18:30 UTC;
        # the range must end just before that, not at UTC day-end.
        self.assertEqual(end_dt, datetime(2026, 7, 29, 18, 29, 59, 999999))

    def test_event_just_after_ist_midnight_falls_in_the_right_day(self):
        # 00:00:10 IST on 2026-07-29 is 18:30:10 UTC on 2026-07-28 - the
        # exact case the existing write-side test documents. The OLD
        # naive-combine query for "2026-07-29" would have missed this
        # event entirely (it's before UTC midnight on the 29th).
        event_utc = datetime(2026, 7, 28, 18, 30, 10)  # naive UTC, as stored

        start_dt, end_dt = get_ist_day_range_utc(date(2026, 7, 29))

        self.assertTrue(start_dt <= event_utc <= end_dt)

    def test_event_just_before_utc_midnight_is_excluded_from_wrong_day(self):
        # 23:00 UTC on 2026-07-28 is 04:30 IST on 2026-07-29 - it belongs
        # to IST day 2026-07-29, NOT 2026-07-28, even though its UTC date
        # is the 28th. The OLD query for "2026-07-28" would have wrongly
        # included this (it's within UTC's own 28th).
        event_utc = datetime(2026, 7, 28, 23, 0, 0)

        start_dt, end_dt = get_ist_day_range_utc(date(2026, 7, 28))

        self.assertFalse(start_dt <= event_utc <= end_dt)


if __name__ == "__main__":
    unittest.main()
