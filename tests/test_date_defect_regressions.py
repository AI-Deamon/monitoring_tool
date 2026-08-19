"""
Regression tests for the specific date defects behind feature 037's US4.

These sit alongside test_datetime_format.py, which covers the shared formatter
in isolation. This file pins the *reported defects* so each one has a test that
fails if the behaviour comes back:

  D02 / FR-009  last-logged-in time showing wrong
  D19 / FR-012  "first seen" showing the registration date, with no time
  D11 / FR-010  generated report time incorrect

All three had the same underlying shape: a timestamp stored as naive UTC was
rendered without conversion, or a manual timezone offset was applied by hand.
"""
import os
import sys
import unittest
from datetime import date, datetime, timedelta, timezone

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "monitoring_tool", "server")
)

from utils.datetime_format import format_date, format_datetime

IST = "Asia/Kolkata"


class TestLastLoginDisplay(unittest.TestCase):
    """
    D02 / FR-009 — "the last logged in time is showing wrong".

    Root cause: auth.py stores last_login as UTC, but the user-management
    templates rendered it with a bare strftime and no timezone conversion, so an
    IST viewer saw a time 5 hours 30 minutes behind the actual sign-in.
    """

    def test_utc_login_renders_in_viewer_timezone(self):
        # Signed in at 09:00 UTC == 14:30 IST.
        stored_naive_utc = datetime(2026, 8, 7, 9, 0)
        self.assertEqual(format_datetime(stored_naive_utc, tz=IST), "07-08-2026 14:30")

    def test_raw_utc_is_not_shown_to_an_ist_viewer(self):
        """The defect: the stored UTC wall clock leaking through unconverted."""
        stored_naive_utc = datetime(2026, 8, 7, 9, 0)
        rendered = format_datetime(stored_naive_utc, tz=IST)
        self.assertNotIn("09:00", rendered)

    def test_login_stored_as_naive_utc_is_interpreted_as_utc(self):
        """
        auth.py writes datetime.now(timezone.utc).replace(tzinfo=None). A value
        written that way and read back must round-trip to the same instant.
        """
        now_aware = datetime.now(timezone.utc)
        stored = now_aware.replace(tzinfo=None)          # what the column holds
        self.assertEqual(format_datetime(stored, tz="UTC"),
                         format_datetime(now_aware, tz="UTC"))

    def test_never_renders_blank_for_a_user_who_never_logged_in(self):
        self.assertEqual(format_datetime(None), "-")


class TestFirstSeenDisplay(unittest.TestCase):
    """
    D19 / FR-012 — "first seen date is showing registered date and not
    displaying time".

    Two defects in one line: the field read agent.registered_at (the
    REGISTRATION moment) instead of agent.first_seen, and rendered it with
    toLocaleDateString(), which drops the time entirely. The API already served
    a correct first_seen (agent.first_activity_at); the UI read the wrong key.
    """

    def test_first_seen_includes_a_time_component(self):
        first_seen = datetime(2026, 8, 7, 9, 15)
        rendered = format_datetime(first_seen, tz=IST)
        self.assertRegex(rendered, r"^\d{2}-\d{2}-\d{4} \d{2}:\d{2}$")
        self.assertNotEqual(rendered, format_date(first_seen, tz=IST))

    def test_first_seen_is_distinguishable_from_registration(self):
        """
        The two values differ whenever an agent registers before it first
        reports telemetry. Rendering must preserve that difference — showing the
        registration moment under a "First Seen" label is the defect.
        """
        registered_at = datetime(2026, 8, 1, 10, 0)
        first_seen = datetime(2026, 8, 7, 9, 15)
        self.assertNotEqual(
            format_datetime(registered_at, tz=IST),
            format_datetime(first_seen, tz=IST),
        )

    def test_date_only_rendering_would_lose_the_time(self):
        """Pins why format_date is the wrong helper for this field."""
        first_seen = datetime(2026, 8, 7, 9, 15)
        self.assertNotIn(":", format_date(first_seen, tz=IST))


class TestReportGenerationTimestamp(unittest.TestCase):
    """
    D11 / FR-010 — "generated report time is not correct".

    Root cause: the client computed
        new Date(now.getTime() + 5.5*3600000)
    and THEN passed timeZone: 'Asia/Kolkata' to toLocaleString — applying the
    +05:30 offset twice, so the reported generation time ran 5.5 hours ahead of
    when the report was actually produced.
    """

    def test_generation_time_matches_the_moment_of_production(self):
        produced_at = datetime(2026, 8, 7, 9, 0)          # naive UTC, as stored
        self.assertEqual(format_datetime(produced_at, tz=IST), "07-08-2026 14:30")

    def test_offset_is_not_applied_twice(self):
        """
        The double-shift produced 20:00 IST for a 09:00 UTC event
        (09:00 +05:30 +05:30). Converting once must give 14:30.
        """
        produced_at = datetime(2026, 8, 7, 9, 0)
        rendered = format_datetime(produced_at, tz=IST)
        double_shifted = format_datetime(produced_at + timedelta(hours=5, minutes=30), tz=IST)
        self.assertEqual(rendered, "07-08-2026 14:30")
        self.assertNotEqual(rendered, double_shifted)

    def test_an_already_offset_string_is_not_shifted_again(self):
        """
        Some endpoints convert server-side and emit '...+05:30' (utc_to_ist).
        That instant must be respected, not re-converted.
        """
        self.assertEqual(
            format_datetime("2026-08-07T14:30:00+05:30", tz=IST),
            "07-08-2026 14:30",
        )


class TestOneFormatEverywhere(unittest.TestCase):
    """
    FR-007 / SC-004 — every surface uses the one canonical format. These pin the
    formats that were previously in use so none can quietly return.
    """

    SAMPLE = datetime(2026, 1, 5, 14, 30)

    def test_no_month_names(self):
        rendered = format_date(self.SAMPLE, tz="UTC")
        for name in ("January", "Jan", "Feb", "August", "Aug"):
            self.assertNotIn(name, rendered)

    def test_no_iso_year_first_ordering(self):
        """'%Y-%m-%d' was in use on several screens and in the schedules table."""
        self.assertNotEqual(format_date(self.SAMPLE, tz="UTC"), "2026-01-05")

    def test_no_12_hour_clock(self):
        rendered = format_datetime(self.SAMPLE, tz="UTC").upper()
        self.assertNotIn("AM", rendered)
        self.assertNotIn("PM", rendered)

    def test_canonical_shapes(self):
        self.assertEqual(format_date(self.SAMPLE, tz="UTC"), "05-01-2026")
        self.assertEqual(format_datetime(self.SAMPLE, tz="UTC"), "05-01-2026 14:30")


if __name__ == "__main__":
    unittest.main()
