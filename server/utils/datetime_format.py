"""
Shared date/time presentation for the dashboard, reports and emails.

Feature 037, US4/US5. Contract:
`specs/037-v4-qa-defect-fixes/contracts/datetime-format.md`

    dates      DD-MM-YYYY        07-08-2026
    date-times DD-MM-YYYY HH:mm  07-08-2026 14:30   (24-hour, zero-padded)
    timestamps DD-MM-YYYY HH:mm:ss 07-08-2026 14:30:00
               (only where second precision is needed, e.g. "Generated on"
               report footers)

Six reported defects (D02, D08, D10, D11, D14, D19) were one missing
abstraction rather than six bugs: there was no shared formatter anywhere, so 92
sites across 23 files each formatted independently and inconsistently. Fixing
the reported screens one at a time would have left every unreported site broken
and guaranteed a seventh report on the next screen built.

**Every user-visible date must go through this module.** Do not add a local
`strftime`, and never use a bare `toLocaleDateString()` on the client — that
follows the *browser's* locale, so the same screen renders differently for
different users, which is why several of these defects could never be
reproduced consistently.

Timezone rules (FR-008, FR-008a):
  - Render in the VIEWER's timezone.
  - When that cannot be determined, fall back to the SERVER's timezone and
    label it, so a viewer is never left assuming a value is in their own local
    time.
  - The same resolution drives `day_range_utc`, so a date filter and the times
    displayed beside it can never disagree (FR-011).

Storage note: every stored timestamp is naive UTC
(`server_telemetry.parse_agent_timestamp` normalizes on write), so a naive input
here is interpreted as UTC — never as local time.
"""
import logging
import os
from datetime import date as _date
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger(__name__)

# The single canonical format. Day first, numeric month, 24-hour clock.
DATE_FORMAT = "%d-%m-%Y"
DATETIME_FORMAT = "%d-%m-%Y %H:%M"
# Seconds variant: only for values where second precision is required
# (report "Generated on" footers). Not for general display.
DATETIME_SECONDS_FORMAT = "%d-%m-%Y %H:%M:%S"

# Shown when a value is absent. Explicitly unknown beats a misleading default
# (FR-017).
EMPTY_DISPLAY = "-"

# Server timezone used when the viewer's cannot be determined (FR-008a).
# Environment-configurable per Constitution Principle I.
_SERVER_TZ_NAME = os.getenv("DISPLAY_TIMEZONE", "UTC")


def server_timezone() -> ZoneInfo:
    """The fallback timezone. Never raises — an unusable name degrades to UTC."""
    try:
        return ZoneInfo(_SERVER_TZ_NAME)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        logger.warning(
            "[DATETIME] DISPLAY_TIMEZONE=%r is not a known zone; using UTC",
            _SERVER_TZ_NAME,
        )
        return ZoneInfo("UTC")


def resolve_timezone(tz=None) -> ZoneInfo:
    """
    Resolve the timezone to render in.

    Accepts an IANA name, a ZoneInfo, or None. An unknown or unusable value
    falls back to the server timezone rather than raising — a formatting helper
    must never be able to break a page (FR-008a).
    """
    if isinstance(tz, ZoneInfo):
        return tz
    if tz:
        try:
            return ZoneInfo(str(tz))
        except (ZoneInfoNotFoundError, ValueError, KeyError):
            logger.debug("[DATETIME] Unknown timezone %r; falling back to server", tz)
    return server_timezone()


def timezone_label(tz=None) -> str:
    """
    Human-readable label for the timezone in use. Never empty — FR-008 requires
    the viewer to always be able to tell which clock a value is expressed in.
    """
    return str(resolve_timezone(tz))


def _coerce(value):
    """
    Accept the shapes callers actually hold: date, datetime, or ISO-8601 string.

    Strings matter more than they look. `report_engine` builds context values
    like `'date': ...strftime('%Y-%m-%d')`, templates render those directly, and
    API payloads are strings by the time anything formats them. A formatter that
    only accepted datetimes would raise AttributeError on exactly those paths.

    Returns None for anything unparseable, so a bad value renders as
    EMPTY_DISPLAY rather than breaking the page.
    """
    if value is None or value == '':
        return None
    if isinstance(value, datetime) or isinstance(value, _date):
        return value
    if isinstance(value, str):
        text = value.strip().replace('Z', '+00:00')
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            try:
                return _date.fromisoformat(text[:10])
            except ValueError:
                logger.debug("[DATETIME] Unparseable value %r", value)
                return None
    return None


def to_display_tz(value, tz=None):
    """
    Convert a stored timestamp into the display timezone.

    A naive value is interpreted as UTC, matching how timestamps are stored.
    Returns None for a missing or unparseable value so callers render
    EMPTY_DISPLAY.
    """
    value = _coerce(value)
    if value is None:
        return None
    if isinstance(value, _date) and not isinstance(value, datetime):
        # A plain date carries no time and therefore no timezone to convert.
        return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(resolve_timezone(tz))


def format_date(value, tz=None) -> str:
    """Render a date as DD-MM-YYYY. Missing values render as EMPTY_DISPLAY."""
    converted = to_display_tz(value, tz)
    if converted is None:
        return EMPTY_DISPLAY
    return converted.strftime(DATE_FORMAT)


def format_datetime(value, tz=None) -> str:
    """Render a timestamp as DD-MM-YYYY HH:mm. Missing values render as EMPTY_DISPLAY."""
    converted = to_display_tz(value, tz)
    if converted is None:
        return EMPTY_DISPLAY
    return converted.strftime(DATETIME_FORMAT)


def format_datetime_labelled(value, tz=None) -> str:
    """As format_datetime, with the timezone appended (FR-008)."""
    converted = to_display_tz(value, tz)
    if converted is None:
        return EMPTY_DISPLAY
    return f"{converted.strftime(DATETIME_FORMAT)} ({timezone_label(tz)})"


def format_datetime_seconds(value, tz=None) -> str:
    """Render a timestamp as DD-MM-YYYY HH:mm:ss. Missing values render as EMPTY_DISPLAY."""
    converted = to_display_tz(value, tz)
    if converted is None:
        return EMPTY_DISPLAY
    return converted.strftime(DATETIME_SECONDS_FORMAT)


def format_datetime_seconds_labelled(value, tz=None) -> str:
    """As format_datetime_seconds, with the timezone appended (FR-008)."""
    converted = to_display_tz(value, tz)
    if converted is None:
        return EMPTY_DISPLAY
    return f"{converted.strftime(DATETIME_SECONDS_FORMAT)} ({timezone_label(tz)})"


def day_range_utc(target_date, tz=None):
    """
    Return the naive-UTC (start, end) bounds covering one calendar day in the
    display timezone (FR-011).

    Stored columns hold naive UTC, so a plain `datetime.combine(target_date,...)`
    does not shift by the display zone's offset and silently queries the wrong
    window — the cause of D04, where selecting today returned yesterday's
    browsing history. This performs the real conversion first.

    Bounds are half-open in effect: `end` is one microsecond before the next
    day's start, so adjacent days neither overlap nor leave a gap and every
    record falls on exactly one day (FR-011a).

    Generalises `server_dashboard.get_ist_day_range_utc`, which hardcoded +05:30.
    """
    zone = resolve_timezone(tz)
    local_midnight = datetime.combine(target_date, time.min, tzinfo=zone)
    start_dt = local_midnight.astimezone(timezone.utc).replace(tzinfo=None)
    end_dt = (
        (local_midnight + timedelta(days=1)).astimezone(timezone.utc).replace(tzinfo=None)
        - timedelta(microseconds=1)
    )
    return start_dt, end_dt


def today_in(tz=None) -> _date:
    """Today's calendar date in the display timezone — 'today' means the viewer's today."""
    return datetime.now(resolve_timezone(tz)).date()


# Name of the cookie the dashboard sets with the viewer's IANA timezone.
# A cookie rather than a query parameter so every request carries it without
# each call site having to remember to append it.
VIEWER_TZ_COOKIE = "viewer_tz"


def viewer_timezone() -> ZoneInfo:
    """
    The timezone to render and filter in for the current request (FR-008,
    FR-011).

    Resolution order:
      1. the `viewer_tz` cookie, set once by the dashboard from
         Intl.DateTimeFormat().resolvedOptions().timeZone
      2. an `X-Timezone` header (for API clients that set it explicitly)
      3. a `tz` query parameter (useful for links and debugging)
      4. the server timezone — the documented fallback (FR-008a)

    Safe outside a request context: returns the server timezone rather than
    raising, so background jobs and report rendering can call it freely.
    """
    try:
        from flask import has_request_context, request
        if has_request_context():
            candidate = (
                request.cookies.get(VIEWER_TZ_COOKIE)
                or request.headers.get("X-Timezone")
                or request.args.get("tz")
            )
            if candidate:
                return resolve_timezone(candidate)
    except Exception:
        # Flask absent, or request teardown mid-flight. Fall back rather than
        # let a display concern break a query.
        pass
    return server_timezone()
