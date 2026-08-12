"""
D04 / US5 — selecting a date must return that date's records and no other's.

Reported: "On selecting current date, browser history is displaying yesterday's
browsing history."

Two distinct causes, and shipping only one leaves the defect visible:

  1. INGESTION (spec 034). The /domains route parsed the agent's offset-aware
     timestamp then called .replace(tzinfo=None), DISCARDING the offset instead
     of applying it. An IST agent's 20:15+05:30 was stored as naive 20:15
     instead of the true UTC 14:45 — every row ~5.5h later than reality, so
     yesterday evening's entries fall inside today's window. The fix exists in
     the working tree but was never committed (see investigation-findings.md),
     so no build QA tested contains it.

  2. FILTERING (FR-011). The day boundary was hardcoded to IST. A selected date
     must resolve using the same timezone the timestamps are DISPLAYED in, or
     the filter and the display disagree about which day a record belongs to.

These tests pin the filtering contract. The ingestion contract is pinned by
parse_agent_timestamp's own tests.
"""
import os
import sys
import unittest
from datetime import date, datetime, timedelta, timezone

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "monitoring_tool", "server")
)

from utils.datetime_format import day_range_utc

IST = "Asia/Kolkata"      # +05:30, no DST
NY = "America/New_York"   # -04:00 in August


def _stored(local_dt, tz_offset_hours, tz_offset_minutes=0):
    """
    The naive-UTC value the database SHOULD hold for a wall-clock reading on an
    agent at the given offset. This is what parse_agent_timestamp produces.
    """
    offset = timezone(timedelta(hours=tz_offset_hours, minutes=tz_offset_minutes))
    return local_dt.replace(tzinfo=offset).astimezone(timezone.utc).replace(tzinfo=None)


def _falls_in(stored_naive_utc, target_date, tz):
    start, end = day_range_utc(target_date, tz=tz)
    return start <= stored_naive_utc <= end


class TestTodayExcludesYesterday(unittest.TestCase):
    """The reported symptom, stated as an assertion."""

    def test_yesterday_evening_is_not_in_todays_window(self):
        # 18:39 IST yesterday — one of the exact times in QA's report.
        yesterday_evening = _stored(datetime(2026, 8, 6, 18, 39), 5, 30)
        self.assertFalse(
            _falls_in(yesterday_evening, date(2026, 8, 7), IST),
            "yesterday evening must not appear under today",
        )
        self.assertTrue(
            _falls_in(yesterday_evening, date(2026, 8, 6), IST),
            "yesterday evening belongs to yesterday",
        )

    def test_late_yesterday_evening_is_not_in_todays_window(self):
        # 21:21 IST yesterday — also from the report.
        late = _stored(datetime(2026, 8, 6, 21, 21), 5, 30)
        self.assertFalse(_falls_in(late, date(2026, 8, 7), IST))
        self.assertTrue(_falls_in(late, date(2026, 8, 6), IST))

    def test_todays_morning_is_in_todays_window(self):
        morning = _stored(datetime(2026, 8, 7, 10, 26), 5, 30)
        self.assertTrue(_falls_in(morning, date(2026, 8, 7), IST))

    def test_just_after_midnight_belongs_to_the_new_day(self):
        # 00:26 IST — in QA's report as a genuine "today" entry.
        just_after = _stored(datetime(2026, 8, 7, 0, 26), 5, 30)
        self.assertTrue(_falls_in(just_after, date(2026, 8, 7), IST))
        self.assertFalse(_falls_in(just_after, date(2026, 8, 6), IST))


class TestMidnightBoundary(unittest.TestCase):
    """
    FR-011a / SC-006 — a record five minutes either side of local midnight must
    land on exactly one day. Never both, never neither.
    """

    def test_five_minutes_before_midnight(self):
        before = _stored(datetime(2026, 8, 6, 23, 55), 5, 30)
        self.assertTrue(_falls_in(before, date(2026, 8, 6), IST))
        self.assertFalse(_falls_in(before, date(2026, 8, 7), IST))

    def test_five_minutes_after_midnight(self):
        after = _stored(datetime(2026, 8, 7, 0, 5), 5, 30)
        self.assertTrue(_falls_in(after, date(2026, 8, 7), IST))
        self.assertFalse(_falls_in(after, date(2026, 8, 6), IST))

    def test_exactly_midnight_belongs_to_the_starting_day(self):
        midnight = _stored(datetime(2026, 8, 7, 0, 0), 5, 30)
        self.assertTrue(_falls_in(midnight, date(2026, 8, 7), IST))
        self.assertFalse(_falls_in(midnight, date(2026, 8, 6), IST))

    def test_no_record_can_fall_on_two_days(self):
        """Sweep the whole boundary minute by minute — no double counting."""
        base = datetime(2026, 8, 6, 23, 55)
        for minute in range(11):                       # 23:55 .. 00:05
            stored = _stored(base + timedelta(minutes=minute), 5, 30)
            days = [d for d in (date(2026, 8, 6), date(2026, 8, 7))
                    if _falls_in(stored, d, IST)]
            self.assertEqual(
                1, len(days),
                f"{base + timedelta(minutes=minute)} IST fell on {len(days)} days",
            )

    def test_no_record_falls_through_the_gap(self):
        """The inverse: every instant in the boundary window belongs somewhere."""
        start_prev, end_prev = day_range_utc(date(2026, 8, 6), tz=IST)
        start_next, _ = day_range_utc(date(2026, 8, 7), tz=IST)
        self.assertLess(end_prev, start_next)
        self.assertLess(start_next - end_prev, timedelta(seconds=1))


class TestFilterFollowsDisplayTimezone(unittest.TestCase):
    """
    FR-011 — the boundary uses the same timezone as display. If the two ever
    disagree, a selected date returns records whose displayed times contradict
    it, which is the defect in a subtler form.
    """

    def test_same_instant_maps_to_different_days_in_different_zones(self):
        # 02:00 IST on the 7th == 20:30 UTC on the 6th == 16:30 New York on the 6th.
        stored = _stored(datetime(2026, 8, 7, 2, 0), 5, 30)
        self.assertTrue(_falls_in(stored, date(2026, 8, 7), IST))
        self.assertTrue(_falls_in(stored, date(2026, 8, 6), "UTC"))
        self.assertTrue(_falls_in(stored, date(2026, 8, 6), NY))

    def test_dst_zone_boundary_is_handled(self):
        """New York is -04:00 in August; local midnight is 04:00 UTC."""
        start, _ = day_range_utc(date(2026, 8, 7), tz=NY)
        self.assertEqual(start, datetime(2026, 8, 7, 4, 0))

    def test_unknown_timezone_falls_back_without_raising(self):
        """FR-008a — a bad zone must degrade, never break the query."""
        start, end = day_range_utc(date(2026, 8, 7), tz="Not/AZone")
        self.assertIsNotNone(start)
        self.assertLess(start, end)


class TestExistingIstBehaviourPreserved(unittest.TestCase):
    """
    T057 — the shipped IST helper must keep producing identical bounds, so
    nothing that relies on it regresses while the viewer-aware path is added.
    """

    def test_matches_the_shipped_helper_across_a_year(self):
        from server_dashboard import get_ist_day_range_utc
        for offset in range(0, 365, 17):
            d = date(2026, 1, 1) + timedelta(days=offset)
            self.assertEqual(
                day_range_utc(d, tz=IST), get_ist_day_range_utc(d),
                f"diverged from the shipped IST helper on {d}",
            )


if __name__ == "__main__":
    unittest.main()
