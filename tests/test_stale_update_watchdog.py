"""
Tests for background_tasks.check_stale_updates() (the stale-update watchdog).

Bug: the watchdog judged staleness by Agent.last_update_check, which
refreshes on every successful poll regardless of outcome. An agent that
polls on schedule but silently rejects the update every time (e.g. a
signature mismatch) never looks stale, so it can sit at update_status=
'pending' for days without ever being auto-reset. The fix derives
staleness from UpdateHistory instead - specifically from when the
agent's CURRENT episode (scoped by target_version) last showed real
progress, not from its last chatty re-affirmation of the same pending
state.

No real database is used anywhere in this file - server_models.Agent
and server_models.UpdateHistory are fully mocked. (This codebase's
server_config.py calls load_dotenv(override=True), so an
os.environ.setdefault('DATABASE_URL', ...) guard does NOT actually
isolate from the real dev Postgres DB the way it looks like it should -
only full mocking does.)
"""

import sys
import types
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, __file__.rsplit('tests', 1)[0] + 'server')

import background_tasks  # noqa: E402


def _agent(agent_id='a1', hostname='H1', update_status='pending',
           target_version='4.2.1', last_update_check=None):
    return SimpleNamespace(
        agent_id=agent_id, hostname=hostname, update_status=update_status,
        target_version=target_version, last_update_check=last_update_check,
    )


class TestUpdateEpisodeReferenceTime:
    """Unit tests for the staleness-reference helper in isolation."""

    def _mock_server_models(self, progress_row=None, pending_rows=None,
                             terminal_row=None):
        """
        Three independent query chains are built off UpdateHistory.query, in
        this call order: last_terminal (filter_by -> filter -> order_by ->
        first), progress (filter_by -> filter -> [filter] -> order_by ->
        first), pending (filter_by -> [filter] -> order_by -> all) - the
        bracketed filter() is the conditional since-scoping added by the
        review fix. Each filter_by() call must return its OWN chain object
        (via side_effect) so the three don't bleed into each other, and each
        chain absorbs any number of .filter() calls via filter.return_value
        = self, so it doesn't matter whether the since-scoping filter was
        actually applied. pending_rows must already be in ascending
        created_at order, matching what the real ORDER BY produces.
        """
        def _chain(first_value=None, all_value=None):
            q = MagicMock()
            q.filter.return_value = q
            q.order_by.return_value = q
            q.first.return_value = first_value
            q.all.return_value = all_value or []
            return q

        sm = MagicMock()
        sm.UpdateHistory.query.filter_by = MagicMock(side_effect=[
            _chain(first_value=terminal_row),
            _chain(first_value=progress_row),
            _chain(all_value=pending_rows),
        ])
        # Real SQLAlchemy columns overload `>` to build a SQL expression;
        # plain MagicMock doesn't support ordering comparisons at all
        # (raises TypeError), so the since-scoping `created_at > since`
        # comparison needs an explicit stand-in here.
        sm.UpdateHistory.created_at.__gt__ = MagicMock(return_value=MagicMock())
        return sm

    def test_progress_row_wins_over_pending(self):
        progress_ts = datetime(2026, 8, 5, 10, 0, 0)
        pending_ts = datetime(2026, 7, 28, 10, 0, 0)
        sm = self._mock_server_models(
            progress_row=SimpleNamespace(created_at=progress_ts),
            pending_rows=[SimpleNamespace(created_at=pending_ts)],
        )
        agent = _agent()

        result = background_tasks._update_episode_reference_time(agent, sm)

        assert result == progress_ts, (
            "an agent actually downloading/installing must be judged by "
            "that progress, not by when it first went pending"
        )

    def test_falls_back_to_earliest_pending_when_no_progress(self):
        pending_ts = datetime(2026, 7, 28, 10, 41, 40)
        sm = self._mock_server_models(
            progress_row=None,
            pending_rows=[SimpleNamespace(created_at=pending_ts)],
        )
        agent = _agent()

        result = background_tasks._update_episode_reference_time(agent, sm)

        assert result == pending_ts, (
            "this is the actual fix: judge by when the stuck episode began, "
            "not by the most recent re-affirmation"
        )

    def test_ignores_orphaned_pending_row_across_a_large_gap(self):
        """Review fix #2: an old pending row separated from the current run
        by a gap larger than RESET_GAP (60min) belongs to a disconnected,
        already-abandoned attempt (e.g. cleared via retryUpdate() without a
        terminal row) - the episode start must be the row that begins the
        CURRENT run, not the absolute-oldest row in the table."""
        orphaned_ts = datetime(2026, 8, 6, 5, 41, 34)
        fresh_ts = datetime(2026, 8, 7, 6, 56, 18)
        sm = self._mock_server_models(
            progress_row=None,
            pending_rows=[
                SimpleNamespace(created_at=orphaned_ts),
                SimpleNamespace(created_at=fresh_ts),
            ],
        )
        agent = _agent()

        result = background_tasks._update_episode_reference_time(agent, sm)

        assert result == fresh_ts, (
            f"got {result}, expected the fresh row {fresh_ts} - the >24h gap "
            "to the orphaned row should have reset the episode boundary"
        )

    def test_no_gap_still_uses_true_earliest_pending(self):
        """The original bug scenario must still work: an agent repolling
        every ~20-30min with no progress has small gaps throughout, so the
        TRUE earliest row is still correctly used as the episode start."""
        rows = [
            SimpleNamespace(created_at=datetime(2026, 8, 5, 10, 0, 0)),
            SimpleNamespace(created_at=datetime(2026, 8, 5, 10, 25, 0)),
            SimpleNamespace(created_at=datetime(2026, 8, 5, 10, 50, 0)),
            SimpleNamespace(created_at=datetime(2026, 8, 5, 11, 15, 0)),
        ]
        sm = self._mock_server_models(progress_row=None, pending_rows=rows)
        agent = _agent()

        result = background_tasks._update_episode_reference_time(agent, sm)

        assert result == rows[0].created_at

    def test_falls_back_to_last_update_check_when_no_history_at_all(self):
        luc = datetime(2026, 8, 1, 0, 0, 0)
        sm = self._mock_server_models(progress_row=None, pending_rows=[])
        agent = _agent(last_update_check=luc)

        result = background_tasks._update_episode_reference_time(agent, sm)

        assert result == luc

    def test_falls_back_to_last_update_check_when_only_resolved_episode_exists(self):
        """Review fix: a terminal row alone (re-queued but no new progress/
        pending row has landed yet this cycle) must not be mistaken for 'no
        history at all' in a way that resurrects the OLD episode's rows -
        it must still fall back cleanly rather than crash or misclassify."""
        luc = datetime(2026, 8, 1, 0, 0, 0)
        sm = self._mock_server_models(
            progress_row=None, pending_rows=[],
            terminal_row=SimpleNamespace(created_at=datetime(2026, 7, 20, 0, 0, 0)),
        )
        agent = _agent(last_update_check=luc)

        result = background_tasks._update_episode_reference_time(agent, sm)

        assert result == luc


class TestCheckStaleUpdates:
    """
    check_stale_updates() classification/reset behavior, with
    _update_episode_reference_time patched out so these tests are only
    about the watchdog's decision logic, not the UpdateHistory query
    mechanics (covered above).
    """

    def _run(self, agents, reference_times, monkeypatch):
        fake_sm = types.ModuleType('server_models')
        fake_sm.Agent = MagicMock()
        fake_sm.Agent.query.filter.return_value.all.return_value = agents
        fake_sm.UpdateHistory = MagicMock()

        fake_db = MagicMock()

        def fake_reference_time(agent, server_models):
            return reference_times.get(agent.agent_id)

        with patch.dict(sys.modules, {'server_models': fake_sm}), \
                patch.dict(sys.modules, {'extensions': types.ModuleType('extensions')}):
            sys.modules['extensions'].db = fake_db
            with patch.object(background_tasks, '_update_episode_reference_time',
                              side_effect=fake_reference_time):
                background_tasks.check_stale_updates()

        return fake_db

    def test_agent_stuck_over_60_min_is_reset(self, monkeypatch):
        now = datetime.now(timezone.utc)
        stuck_agent = _agent(agent_id='stuck', update_status='pending')
        reference_times = {'stuck': now - timedelta(hours=5)}

        fake_db = self._run([stuck_agent], reference_times, monkeypatch)

        assert stuck_agent.update_status == 'up_to_date'
        assert stuck_agent.target_version is None
        assert 'Auto-reset by watchdog' in stuck_agent.last_update_error
        fake_db.session.commit.assert_called_once()

    def test_agent_stuck_30_to_60_min_is_only_warned(self, monkeypatch):
        now = datetime.now(timezone.utc)
        warn_agent = _agent(agent_id='warn', update_status='downloading')
        reference_times = {'warn': now - timedelta(minutes=45)}

        self._run([warn_agent], reference_times, monkeypatch)

        assert warn_agent.update_status == 'downloading', (
            "30-60 min is a warning, not a reset"
        )
        assert warn_agent.target_version is not None

    def test_agent_stuck_under_30_min_is_untouched(self, monkeypatch):
        now = datetime.now(timezone.utc)
        fresh_agent = _agent(agent_id='fresh', update_status='pending')
        reference_times = {'fresh': now - timedelta(minutes=5)}

        self._run([fresh_agent], reference_times, monkeypatch)

        assert fresh_agent.update_status == 'pending'
        assert fresh_agent.target_version is not None

    def test_the_actual_bug_scenario_repeated_polling_without_progress(self, monkeypatch):
        """
        This is exactly the observed production case: an agent that keeps
        polling successfully (so a last_update_check-based check would
        never fire) but never progresses past 'pending' for days. The
        reference time here represents the earliest pending row for the
        CURRENT episode, which is what _update_episode_reference_time
        would actually return in that situation - confirming the watchdog
        now acts on it.
        """
        now = datetime.now(timezone.utc)
        stuck_agent = _agent(agent_id='real-stuck', update_status='pending',
                              target_version='4.2.1')
        # Episode began 5 days ago and was never resolved, even though the
        # agent has been polling the whole time (which is why the OLD
        # last_update_check-based check would have missed this).
        reference_times = {'real-stuck': now - timedelta(days=5)}

        fake_db = self._run([stuck_agent], reference_times, monkeypatch)

        assert stuck_agent.update_status == 'up_to_date'
        fake_db.session.commit.assert_called_once()
