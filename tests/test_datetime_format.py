"""
Shared date/time presentation (feature 037, US4 / US5).

Contract: specs/037-v4-qa-defect-fixes/contracts/datetime-format.md
  - dates      -> DD-MM-YYYY        (07-08-2026)
  - date-times -> DD-MM-YYYY HH:mm  (07-08-2026 14:30), 24-hour, zero-padded
  - rendered in the VIEWER's timezone, falling back to the SERVER's when the
    viewer's cannot be determined (FR-008a), always labelled
  - the same timezone resolution drives date filtering, so a selected date can
    never disagree with the times displayed beside it (FR-011)

Six reported defects (D02, D08, D10, D11, D14, D19) are one missing abstraction:
there was no shared formatter, so 92 sites across 23 files each formatted
independently. Notably, a bare toLocaleDateString() follows the *browser's*
locale, so the same screen rendered differently for different users — which is
why several reports could never be reproduced consistently.

Stored timestamps are naive UTC (server_telemetry.parse_agent_timestamp
normalizes every agent timestamp on write), so the formatter must treat a naive
input as UTC rather than as local time.
"""
import os
import sys
import unittest
from datetime import date, datetime, timedelta, timezone

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "monitoring_tool", "server")
)

from utils.datetime_format import (
    DATE_FORMAT,
    DATETIME_FORMAT,
    day_range_utc,
    format_date,
    format_datetime,
    resolve_timezone,
    timezone_label,
)

IST = "Asia/Kolkata"          # +05:30
NY = "America/New_York"       # -04:00 in August (DST)


class TestFormatStrings(unittest.TestCase):
    def test_date_format_is_day_first_numeric(self):
        self.assertEqual(DATE_FORMAT, "%d-%m-%Y")

    def test_datetime_format_is_24_hour(self):
        self.assertEqual(DATETIME_FORMAT, "%d-%m-%Y %H:%M")
        self.assertNotIn("%p", DATETIME_FORMAT)
        self.assertNotIn("%I", DATETIME_FORMAT)


class TestFormatDate(unittest.TestCase):
    def test_formats_day_first(self):
        self.assertEqual(format_date(date(2026, 8, 7)), "07-08-2026")

    def test_zero_pads_single_digit_day_and_month(self):
        self.assertEqual(format_date(date(2026, 1, 5)), "05-01-2026")

    def test_month_is_numeric_never_a_name(self):
        out = format_date(date(2026, 8, 7))
        self.assertNotIn("Aug", out)
        self.assertNotIn("August", out)

    def test_accepts_a_datetime(self):
        self.assertEqual(format_date(datetime(2026, 8, 7, 14, 30)), "07-08-2026")

    def test_none_renders_as_placeholder_not_a_crash(self):
        self.assertEqual(format_date(None), "-")


class TestFormatDatetime(unittest.TestCase):
    def test_formats_with_24_hour_clock(self):
        self.assertEqual(
            format_datetime(datetime(2026, 8, 7, 14, 30, tzinfo=timezone.utc), tz="UTC"),
            "07-08-2026 14:30",
        )

    def test_afternoon_is_not_rendered_as_am_pm(self):
        out = format_datetime(datetime(2026, 8, 7, 14, 30, tzinfo=timezone.utc), tz="UTC")
        self.assertNotIn("PM", out.upper())

    def test_midnight_is_zero_zero(self):
        self.assertEqual(
            format_datetime(datetime(2026, 8, 7, 0, 0, tzinfo=timezone.utc), tz="UTC"),
            "07-08-2026 00:00",
        )

    def test_naive_input_is_treated_as_utc(self):
        """Stored timestamps are naive UTC — they must not be read as local time."""
        self.assertEqual(
            format_datetime(datetime(2026, 8, 7, 14, 30), tz="UTC"),
            "07-08-2026 14:30",
        )

    def test_converts_into_the_viewer_timezone(self):
        # 14:30 UTC is 20:00 IST the same day.
        self.assertEqual(
            format_datetime(datetime(2026, 8, 7, 14, 30), tz=IST),
            "07-08-2026 20:00",
        )

    def test_conversion_can_cross_the_date_boundary(self):
        # 20:00 UTC on the 7th is 01:30 IST on the 8th.
        self.assertEqual(
            format_datetime(datetime(2026, 8, 7, 20, 0), tz=IST),
            "08-08-2026 01:30",
        )

    def test_none_renders_as_placeholder(self):
        self.assertEqual(format_datetime(None), "-")


class TestStringInputs(unittest.TestCase):
    """
    Callers hold strings as often as datetimes: report_engine builds context
    values with strftime('%Y-%m-%d'), templates render those directly, and API
    payloads are strings by the time anything formats them. A formatter that
    only accepted datetimes would raise on exactly those paths.
    """

    def test_iso_date_string(self):
        self.assertEqual(format_date("2026-08-07"), "07-08-2026")

    def test_iso_datetime_string_naive_is_utc(self):
        self.assertEqual(format_datetime("2026-08-07T14:30:00", tz="UTC"), "07-08-2026 14:30")

    def test_iso_datetime_string_with_z(self):
        self.assertEqual(format_datetime("2026-08-07T14:30:00Z", tz="UTC"), "07-08-2026 14:30")

    def test_iso_string_with_explicit_offset_is_not_double_shifted(self):
        """
        Some endpoints already convert server-side and emit an offset
        (utc_to_ist -> '...+05:30'). That instant must be respected, not shifted
        again.
        """
        self.assertEqual(
            format_datetime("2026-08-07T20:00:00+05:30", tz="UTC"),
            "07-08-2026 14:30",
        )

    def test_empty_string_renders_as_placeholder(self):
        self.assertEqual(format_date(""), "-")

    def test_unparseable_string_renders_as_placeholder_not_a_crash(self):
        self.assertEqual(format_date("not a date"), "-")


class TestTimezoneResolution(unittest.TestCase):
    """FR-008a — fall back to the server's timezone, and always label it."""

    def test_resolves_a_valid_name(self):
        self.assertIsNotNone(resolve_timezone(IST))

    def test_falls_back_when_name_is_missing(self):
        self.assertIsNotNone(resolve_timezone(None))

    def test_falls_back_when_name_is_invalid(self):
        """An unknown zone must not raise — it must fall back."""
        self.assertIsNotNone(resolve_timezone("Not/AZone"))

    def test_label_is_never_empty(self):
        self.assertTrue(timezone_label(IST))
        self.assertTrue(timezone_label(None))

    def test_label_identifies_the_zone_in_use(self):
        self.assertIn("Kolkata", timezone_label(IST))


class TestDayRangeUtc(unittest.TestCase):
    """
    FR-011 / FR-011a — a selected date resolves to a UTC instant range using the
    same timezone as display, so filtering and display cannot disagree. This
    generalises server_dashboard.get_ist_day_range_utc, which hardcoded +05:30.
    """

    def test_utc_day_is_midnight_to_midnight(self):
        start, end = day_range_utc(date(2026, 8, 7), tz="UTC")
        self.assertEqual(start, datetime(2026, 8, 7, 0, 0))
        self.assertLess(end - datetime(2026, 8, 7, 23, 59, 59), timedelta(seconds=1))

    def test_ist_day_is_shifted_by_the_offset(self):
        """IST midnight on the 7th is 18:30 UTC on the 6th."""
        start, _ = day_range_utc(date(2026, 8, 7), tz=IST)
        self.assertEqual(start, datetime(2026, 8, 6, 18, 30))

    def test_bounds_are_naive_for_comparison_against_stored_utc(self):
        start, end = day_range_utc(date(2026, 8, 7), tz=IST)
        self.assertIsNone(start.tzinfo)
        self.assertIsNone(end.tzinfo)

    def test_matches_the_existing_ist_helper(self):
        """Must not change behaviour for the IST case that already shipped."""
        from server_dashboard import get_ist_day_range_utc
        self.assertEqual(day_range_utc(date(2026, 8, 7), tz=IST),
                         get_ist_day_range_utc(date(2026, 8, 7)))

    def test_adjacent_days_do_not_overlap_or_gap(self):
        """FR-011a: every record falls on exactly one day — never both, never neither."""
        _, end_day1 = day_range_utc(date(2026, 8, 7), tz=IST)
        start_day2, _ = day_range_utc(date(2026, 8, 8), tz=IST)
        self.assertLess(end_day1, start_day2)
        self.assertLess(start_day2 - end_day1, timedelta(seconds=1))

    def test_handles_a_dst_timezone(self):
        """New York is -04:00 in August; midnight local is 04:00 UTC."""
        start, _ = day_range_utc(date(2026, 8, 7), tz=NY)
        self.assertEqual(start, datetime(2026, 8, 7, 4, 0))


class TestViewerTimezoneResolution(unittest.TestCase):
    """
    FR-011 — the server resolves the viewer's timezone per request so date
    FILTERING uses the same zone as display. If the two ever diverge, a selected
    date returns records whose displayed times contradict it.
    """

    def test_falls_back_outside_a_request_context(self):
        """
        Background jobs and report rendering call this with no request in
        flight. It must return the server timezone, never raise.
        """
        from utils.datetime_format import server_timezone, viewer_timezone
        self.assertEqual(str(viewer_timezone()), str(server_timezone()))

    def test_reads_the_cookie_when_a_request_is_in_flight(self):
        from flask import Flask
        from utils.datetime_format import VIEWER_TZ_COOKIE, viewer_timezone

        app = Flask(__name__)
        with app.test_request_context("/", headers={"Cookie": f"{VIEWER_TZ_COOKIE}={IST}"}):
            self.assertEqual(str(viewer_timezone()), IST)

    def test_header_is_honoured(self):
        from flask import Flask
        from utils.datetime_format import viewer_timezone

        app = Flask(__name__)
        with app.test_request_context("/", headers={"X-Timezone": NY}):
            self.assertEqual(str(viewer_timezone()), NY)

    def test_query_parameter_is_honoured(self):
        from flask import Flask
        from utils.datetime_format import viewer_timezone

        app = Flask(__name__)
        with app.test_request_context(f"/?tz={IST}"):
            self.assertEqual(str(viewer_timezone()), IST)

    def test_a_bad_value_falls_back_instead_of_raising(self):
        """A hostile or stale cookie must not be able to break every query."""
        from flask import Flask
        from utils.datetime_format import VIEWER_TZ_COOKIE, server_timezone, viewer_timezone

        app = Flask(__name__)
        with app.test_request_context("/", headers={"Cookie": f"{VIEWER_TZ_COOKIE}=../../etc/passwd"}):
            self.assertEqual(str(viewer_timezone()), str(server_timezone()))


if __name__ == "__main__":
    unittest.main()
