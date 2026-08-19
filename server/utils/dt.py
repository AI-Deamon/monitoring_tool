"""
Storage-side datetime helpers.

Every `db.DateTime` column in this schema is NAIVE UTC — Postgres
`TIMESTAMP WITHOUT TIME ZONE`. That is a deliberate, load-bearing convention
(D02 / FR-009), and `utils.datetime_format` relies on it: it treats a stored
naive value as UTC and converts to the viewer's timezone for display.

Two distinct failures follow from writing an AWARE `datetime.now(timezone.utc)`
into one of those columns:

1. **Silent 5.5-hour skew.** psycopg2 sends the value with its offset;
   Postgres casts `timestamptz` -> `timestamp` using the *session* TimeZone.
   On an IST server the stored wall-clock lands 5:30 ahead of UTC. This is how
   `update_history.started_at` came to read 16:35 for the same instant its
   `created_at` recorded as 11:05 — and why the stale-update watchdog's
   `reference_ts < reset_cutoff` test could never fire.

2. **TypeError on read.** Values come back naive, so comparing one against an
   aware `datetime.now(timezone.utc)` raises "can't compare offset-naive and
   offset-aware datetimes" — which turned the login lockout branch into a 500
   and made the lockout permanent.

Use `utcnow_naive()` for anything written to a column, and `as_naive_utc()` to
normalize a value read back before comparing it.

This module is the single definition; `auth.utcnow_naive` / `auth.as_naive_utc`
re-export these names for callers that already import them from there.
"""

from datetime import datetime, timezone

__all__ = ["utcnow_naive", "as_naive_utc"]


def utcnow_naive() -> datetime:
    """Current UTC time as a NAIVE datetime, ready to store in a column."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def as_naive_utc(value):
    """
    Normalize a datetime to naive UTC.

    An aware value is converted to UTC before its offset is dropped, so the
    instant is preserved rather than reinterpreted. Naive values (the normal
    case for a value read from the DB) and None pass through unchanged.
    """
    if value is not None and value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value
