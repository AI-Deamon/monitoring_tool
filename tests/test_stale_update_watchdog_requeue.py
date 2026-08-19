"""
DB-backed regression test for the version-reuse gap in
background_tasks._update_episode_reference_time() (review fix, see
test_stale_update_watchdog.py for the fully-mocked unit tests).

The mocked unit tests can prove the since-scoping code path doesn't crash,
but not that it actually excludes rows from a resolved prior episode - that
needs a real ORM query against real rows. Same DB-backed pattern as
test_screen_time_span_authority.py (server/.env -> sentinel_test).
"""
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from dotenv import load_dotenv

_env = Path(__file__).parent.parent / "server" / ".env"
load_dotenv(_env, override=True)


@pytest.fixture(scope="module")
def app_context():
    os.environ['FLASK_ENV'] = 'development'
    from server_app import create_app

    app = create_app()
    with app.app_context():
        yield app


@pytest.fixture
def test_agent(app_context):
    from extensions import db
    from sqlalchemy import text

    agent_id = str(uuid.uuid4())
    db.session.execute(
        text("INSERT INTO agents (agent_id, hostname) VALUES (:a, :h)"),
        {'a': agent_id, 'h': 'pytest-requeue-watchdog'},
    )
    db.session.commit()
    yield agent_id
    db.session.rollback()
    db.session.execute(text("DELETE FROM agents WHERE agent_id = :a"),
                       {'a': agent_id})
    db.session.commit()


def _insert_history(agent_id, to_version, status, created_at):
    from extensions import db
    import server_models

    row = server_models.UpdateHistory(
        agent_id=agent_id, from_version='4.0.0', to_version=to_version,
        status=status, created_at=created_at,
    )
    db.session.add(row)
    db.session.commit()


class TestRequeueAfterResolvedEpisode:
    def test_old_failed_episode_does_not_mask_fresh_requeue(
            self, app_context, test_agent):
        """The exact bug scenario: an update to version X failed 5 days ago
        (old pending/failed rows for X still in the table); the SAME version
        X is pushed again and a fresh pending row lands 2 minutes ago. The
        reference time must be the FRESH pending row, not the 5-day-old one
        - otherwise the freshly re-queued agent looks stuck for 5 days and
        gets auto-reset within the next watchdog cycle."""
        from background_tasks import _update_episode_reference_time
        import server_models

        old_pending_ts = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=5)
        old_failed_ts = old_pending_ts + timedelta(minutes=10)
        fresh_pending_ts = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=2)

        _insert_history(test_agent, '5.0.0', 'pending', old_pending_ts)
        _insert_history(test_agent, '5.0.0', 'failed', old_failed_ts)
        _insert_history(test_agent, '5.0.0', 'pending', fresh_pending_ts)

        agent = server_models.Agent.query.filter_by(agent_id=test_agent).first()
        agent.target_version = '5.0.0'
        agent.update_status = 'pending'

        reference_ts = _update_episode_reference_time(agent, server_models)

        assert reference_ts is not None
        assert abs((reference_ts - fresh_pending_ts).total_seconds()) < 1, (
            f"reference time was {reference_ts}, expected ~{fresh_pending_ts} "
            "(the fresh re-queue) - got the old resolved episode's timestamp "
            "instead, which is exactly the bug this fix closes"
        )

    def test_old_failed_episode_alone_falls_back_to_last_update_check(
            self, app_context, test_agent):
        """No fresh row has landed yet this cycle (target_version was just
        reset to the same value server-side, agent hasn't polled again) -
        must not resurrect the old episode's ancient pending row."""
        from background_tasks import _update_episode_reference_time
        import server_models

        old_ts = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=5)
        _insert_history(test_agent, '5.0.0', 'pending', old_ts)
        _insert_history(test_agent, '5.0.0', 'failed', old_ts + timedelta(minutes=10))

        luc = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1)
        agent = server_models.Agent.query.filter_by(agent_id=test_agent).first()
        agent.target_version = '5.0.0'
        agent.update_status = 'pending'
        agent.last_update_check = luc
        from extensions import db
        db.session.commit()

        reference_ts = _update_episode_reference_time(agent, server_models)

        assert reference_ts is not None
        assert abs((reference_ts - luc).total_seconds()) < 1, (
            f"reference time was {reference_ts}, expected ~{luc} "
            "(last_update_check fallback) - the old resolved episode's "
            "5-day-old pending row leaked through instead"
        )

    def test_orphaned_pending_row_with_no_terminal_row_does_not_mask_manual_retarget(
            self, app_context, test_agent):
        """The exact live UAT scenario found today: a manual dashboard
        retarget (api_set_target_version) wrote an old 'pending' row a day
        ago, then the episode was abandoned WITHOUT ever recording a
        terminal outcome (the retryUpdate()/reset path clears update_status
        without logging success/failed/rolled_back - so last_terminal is
        None here, unlike the sibling test above). A second manual retarget
        today writes a fresh 'pending' row. With no terminal row to scope
        past, the reference time must come from the gap-detection fix
        (RESET_GAP), not from the 25-hour-old orphaned row."""
        from background_tasks import _update_episode_reference_time
        import server_models

        orphaned_ts = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=25)
        fresh_ts = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=5)
        _insert_history(test_agent, '4.2.1', 'pending', orphaned_ts)
        _insert_history(test_agent, '4.2.1', 'pending', fresh_ts)

        agent = server_models.Agent.query.filter_by(agent_id=test_agent).first()
        agent.target_version = '4.2.1'
        agent.update_status = 'pending'
        from extensions import db
        db.session.commit()

        reference_ts = _update_episode_reference_time(agent, server_models)

        assert reference_ts is not None
        assert abs((reference_ts - fresh_ts).total_seconds()) < 1, (
            f"reference time was {reference_ts}, expected ~{fresh_ts} - the "
            "25h-old orphaned row (no terminal row separates it from the "
            "fresh retarget) leaked through and would have gotten this "
            "agent auto-reset within one watchdog cycle of being re-queued"
        )
