"""
update_history audit rows: naive-UTC timestamps, and no phantom episodes.

## Defect 1 — started_at stored 5.5 hours ahead

Observed on a live row for agent L180701PB:

    started_at = 2026-08-12 16:35:33.796861
    created_at = 2026-08-12 11:05:33.798416

The same instant, 5:30 apart. `_write_update_history()` assigned an AWARE
`datetime.now(timezone.utc)` to `started_at` / `completed_at`, which are
`db.Column(db.DateTime)` — TIMESTAMP WITHOUT TIME ZONE. psycopg2 sends the
offset, Postgres casts timestamptz -> timestamp through the SESSION TimeZone,
and on an IST server the stored wall-clock lands 5:30 ahead of UTC.
`created_at` was correct because its column default is already naive.

Consequence beyond cosmetics: `_update_episode_reference_time()` feeds
`started_at` to the stale-update watchdog, which tests
`reference_ts < reset_cutoff`. A reference time 5.5 hours in the FUTURE can
never satisfy that, so an agent genuinely stuck mid-update was never
auto-reset — the watchdog was dead for every row it was meant to catch.

## Defect 2 — phantom 'pending' episodes with an empty to_version

`trigger_check` passes `agent.target_version or ''`, and the status map turns
'trigger_check' into 'pending'. Forcing a check on an agent with no target
therefore wrote a `pending` episode for version '' that could never reach a
terminal status. Three such rows existed for L180701PB. That is exactly the
un-anchored row the comment in server_dashboard.api_set_target_version warns
lets the watchdog auto-reset a fresh trigger before the agent ever polls.
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

# Imported at module scope, BEFORE any patching. Patching sys.modules instead
# poisons the import cache: auth executes `class TabSession(db.Model)` at
# import time, so if it first loads while `extensions` is mocked, TabSession
# becomes a Mock subclass and every later test that touches auth fails.
import extensions
import server_models
import server_updates

from utils.dt import as_naive_utc, utcnow_naive


class TestNaiveUtcHelpers:
    def test_utcnow_naive_is_naive(self):
        assert utcnow_naive().tzinfo is None

    def test_utcnow_naive_is_utc_not_local(self):
        drift = abs(
            (utcnow_naive() - datetime.now(timezone.utc).replace(tzinfo=None))
            .total_seconds()
        )
        assert drift < 5, f"utcnow_naive() drifted {drift}s from UTC"

    def test_as_naive_utc_converts_before_dropping_offset(self):
        """An IST value must become its UTC instant, not lose 5:30."""
        from datetime import timedelta

        ist = timezone(timedelta(hours=5, minutes=30))
        aware = datetime(2026, 8, 12, 16, 35, 33, tzinfo=ist)
        assert as_naive_utc(aware) == datetime(2026, 8, 12, 11, 5, 33)

    def test_as_naive_utc_passthrough(self):
        naive = datetime(2026, 8, 12, 11, 5, 33)
        assert as_naive_utc(naive) is naive
        assert as_naive_utc(None) is None


class TestUpdateHistoryTimestamps:
    """Exercises _write_update_history() with the DB layer mocked out."""

    def _capture(self, event, version, agent_version="4.2.2"):
        """Run _write_update_history and return the UpdateHistory kwargs."""
        captured = {}

        class FakeHistory:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        mock_agent = MagicMock()
        mock_agent.version = agent_version

        fake_agent_cls = MagicMock()
        fake_agent_cls.query.filter_by.return_value.first.return_value = mock_agent

        fake_db = MagicMock()

        with patch.object(server_models, "Agent", fake_agent_cls), patch.object(
            server_models, "UpdateHistory", FakeHistory
        ), patch.object(extensions, "db", fake_db):
            server_updates._write_update_history("agent-1", event, version, "details")

        return captured, fake_db

    def test_started_at_is_naive(self):
        captured, _ = self._capture("version_check", "4.2.3")
        assert captured, "no UpdateHistory row was built"
        started = captured["started_at"]
        assert started is not None
        assert started.tzinfo is None, (
            "started_at must be naive — an aware value is shifted by the session "
            "timezone into a TIMESTAMP WITHOUT TIME ZONE column"
        )

    def test_started_at_is_utc_not_local_wallclock(self):
        """
        The regression that mattered: a value 5.5h ahead of UTC reads as a
        future timestamp and disables the stale-update watchdog.
        """
        captured, _ = self._capture("version_check", "4.2.3")
        drift = abs(
            (captured["started_at"] - datetime.now(timezone.utc).replace(tzinfo=None))
            .total_seconds()
        )
        assert drift < 5, (
            f"started_at is {drift}s from UTC — this is the 5.5-hour skew that "
            f"made reference_ts land in the future"
        )

    def test_completed_at_is_naive_for_terminal_events(self):
        captured, _ = self._capture("health_failed", "4.2.3")
        assert captured["completed_at"] is not None
        assert captured["completed_at"].tzinfo is None
        assert captured["started_at"] is None

    def test_started_and_completed_are_mutually_exclusive(self):
        opening, _ = self._capture("status_downloading", "4.2.3")
        assert opening["started_at"] is not None and opening["completed_at"] is None

        closing, _ = self._capture("health_healthy", "4.2.3")
        assert closing["completed_at"] is not None and closing["started_at"] is None


class TestNoPhantomEpisodes:
    """A lifecycle episode must have a target version to be an episode of."""

    def _capture(self, event, version):
        return TestUpdateHistoryTimestamps()._capture(event, version)

    @pytest.mark.parametrize("empty", ["", "   ", None])
    def test_pending_row_is_not_written_without_a_target(self, empty):
        """
        trigger_check passes `agent.target_version or ''`. With no target that
        wrote a 'pending' row for version '' which never terminated.
        """
        captured, fake_db = self._capture("trigger_check", empty)
        assert not captured, (
            f"a phantom episode was written for target {empty!r}: {captured}"
        )
        fake_db.session.add.assert_not_called()

    def test_pending_row_is_written_when_a_target_exists(self):
        captured, _ = self._capture("trigger_check", "4.2.3")
        assert captured["to_version"] == "4.2.3"
        assert captured["status"] == "pending"

    def test_terminal_events_are_still_recorded_without_a_version(self):
        """
        Only OPEN episodes need a target. A failure report must never be
        dropped — that is the audit trail for a broken update.
        """
        captured, _ = self._capture("health_failed", "")
        assert captured, "terminal event was suppressed"
        assert captured["status"] == "failed"
