"""
Reliability tests for the app_usage/domain_usage/screen_time sync jobs
in server_main.py and background_tasks.py.

Bug 1: background_tasks.py's daily sync_yesterday_data() still called
sync_screen_time_from_sessions(), the GREATEST()-ratchet function removed
from the per-minute job in an earlier fix specifically because it can
never self-correct active_seconds downward once inflated by a bad
app_sessions row. The earlier fix only touched the per-minute job.

Bug 2: the per-minute job (server_main.py) passed Postgres's
CURRENT_DATE, which resolves to this database's configured session
timezone (IST, Asia/Calcutta) - but the sync functions filter sessions
with `start_time::DATE = p_date`, and start_time is always stored as
naive UTC. An IST-valued p_date silently mis-buckets sessions in the
~5.5 hour window after IST midnight. The daily job (background_tasks.py)
already computes UTC correctly; the per-minute job must match it.
"""

import inspect
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from unittest.mock import patch


@pytest.fixture
def app_context():
    """Create Flask app context for server tests"""
    import os
    os.environ['FLASK_ENV'] = 'development'  # Avoid SECRET_KEY errors
    from server_app import create_app

    app = create_app()
    with app.app_context():
        yield app


class TestScreenTimeRatchetNotCalled:
    def test_sync_yesterday_data_does_not_call_screen_time_ratchet(self, app_context):
        import background_tasks
        from extensions import db

        executed_sql = []
        original_execute = db.session.execute

        def spy_execute(stmt, *args, **kwargs):
            executed_sql.append(str(stmt))
            return original_execute(stmt, *args, **kwargs)

        with patch.object(db.session, "execute", side_effect=spy_execute):
            background_tasks.sync_yesterday_data()

        assert not any("sync_screen_time_from_sessions" in sql for sql in executed_sql), (
            "sync_yesterday_data() must not call the GREATEST()-ratchet "
            "screen_time function - process_screentime_delta is the "
            "documented authoritative writer for screen_time."
        )
        assert any("sync_app_usage_from_sessions" in sql for sql in executed_sql)
        assert any("sync_domain_usage_from_sessions" in sql for sql in executed_sql)


class TestSyncJobsAgreeOnUtcDate:
    def test_server_main_does_not_use_current_date_for_usage_sync(self):
        # CURRENT_DATE resolves to the DB session's configured timezone
        # (IST on this database), which disagrees with start_time::DATE
        # (always UTC). The per-minute job must pass an explicit UTC date
        # instead, matching background_tasks.py's daily job.
        import server_main

        source = inspect.getsource(server_main.sync_screen_time_background)
        # Check for the actual SQL usage pattern, not just the bare word -
        # the fix's own explanatory comment legitimately mentions
        # "CURRENT_DATE" by name while describing what was removed.
        assert "(CURRENT_DATE)" not in source

    @pytest.fixture
    def test_agent(self, app_context):
        from extensions import db
        from sqlalchemy import text

        agent_id = str(uuid.uuid4())
        db.session.execute(
            text("INSERT INTO agents (agent_id, hostname) VALUES (:a, :h)"),
            {"a": agent_id, "h": "pytest-usage-sync"},
        )
        db.session.commit()
        yield agent_id
        db.session.rollback()
        db.session.execute(text("DELETE FROM agents WHERE agent_id = :a"), {"a": agent_id})
        db.session.commit()

    def test_early_ist_morning_session_buckets_by_utc_date_not_ist_date(
        self, app_context, test_agent
    ):
        from extensions import db
        from sqlalchemy import text

        # 2026-07-11T02:00:00+05:30 (early IST morning, "IST today" if you
        # asked CURRENT_DATE under this DB's IST session timezone) is
        # 2026-07-10T20:30:00 UTC - it belongs to UTC date 2026-07-10, and
        # that's the only date sync_app_usage_from_sessions will actually
        # match it against (start_time::DATE = p_date).
        start = datetime(2026, 7, 10, 20, 30, 0)  # naive UTC, as stored
        end = datetime(2026, 7, 10, 21, 0, 0)
        db.session.execute(
            text(
                "INSERT INTO app_sessions (agent_id, app, start_time, end_time, duration_seconds) "
                "VALUES (:a, :app, :s, :e, :d)"
            ),
            {"a": test_agent, "app": "chrome.exe", "s": start, "e": end, "d": 1800},
        )
        db.session.commit()

        correct_utc_date = start.date()  # 2026-07-10
        db.session.execute(
            text("SELECT sync_app_usage_from_sessions(:d)"), {"d": correct_utc_date}
        )
        db.session.commit()

        row = db.session.execute(
            text(
                "SELECT duration_seconds FROM app_usage "
                "WHERE agent_id = :a AND date = :d AND app = :app"
            ),
            {"a": test_agent, "d": correct_utc_date, "app": "chrome.exe"},
        ).fetchone()

        assert row is not None, (
            "session was not aggregated under its correct UTC date - "
            "confirms start_time::DATE filtering requires a UTC p_date"
        )
        assert row[0] == 1800


class TestUsageSyncCapsAt24Hours:
    @pytest.fixture
    def test_agent(self, app_context):
        from extensions import db
        from sqlalchemy import text

        agent_id = str(uuid.uuid4())
        db.session.execute(
            text("INSERT INTO agents (agent_id, hostname) VALUES (:a, :h)"),
            {"a": agent_id, "h": "pytest-usage-cap"},
        )
        db.session.commit()
        yield agent_id
        db.session.rollback()
        db.session.execute(text("DELETE FROM agents WHERE agent_id = :a"), {"a": agent_id})
        db.session.commit()

    def test_app_usage_sync_caps_oversized_daily_total(self, app_context, test_agent):
        from extensions import db
        from sqlalchemy import text

        # A single oversized/overlapping-retry row summing to more than
        # 24h for one app in one day - should never happen from a single
        # well-formed session, but app_sessions has no overlap protection,
        # so this simulates a retried upload / pre-fix agent bug.
        day = datetime(2026, 7, 15).date()
        db.session.execute(
            text(
                "INSERT INTO app_sessions (agent_id, app, start_time, end_time, duration_seconds) "
                "VALUES (:a, 'chrome.exe', :s, :e, :d)"
            ),
            {
                "a": test_agent,
                "s": datetime(2026, 7, 15, 0, 0, 0),
                "e": datetime(2026, 7, 15, 23, 59, 0),
                "d": 100000,  # ~27.8h - impossible for one calendar day
            },
        )
        db.session.commit()

        db.session.execute(text("SELECT sync_app_usage_from_sessions(:d)"), {"d": day})
        db.session.commit()

        row = db.session.execute(
            text(
                "SELECT duration_seconds FROM app_usage "
                "WHERE agent_id = :a AND date = :d AND app = 'chrome.exe'"
            ),
            {"a": test_agent, "d": day},
        ).fetchone()

        assert row is not None
        assert row[0] <= 86400, f"app_usage.duration_seconds must be capped at 86400, got {row[0]}"

    def test_domain_usage_sync_caps_oversized_daily_total(self, app_context, test_agent):
        from extensions import db
        from sqlalchemy import text

        day = datetime(2026, 7, 16).date()
        db.session.execute(
            text(
                "INSERT INTO domain_sessions (agent_id, domain, start_time, end_time, duration_seconds) "
                "VALUES (:a, 'example.com', :s, :e, :d)"
            ),
            {
                "a": test_agent,
                "s": datetime(2026, 7, 16, 0, 0, 0),
                "e": datetime(2026, 7, 16, 23, 59, 0),
                "d": 100000,
            },
        )
        db.session.commit()

        db.session.execute(text("SELECT sync_domain_usage_from_sessions(:d)"), {"d": day})
        db.session.commit()

        row = db.session.execute(
            text(
                "SELECT duration_seconds FROM domain_usage "
                "WHERE agent_id = :a AND date = :d AND domain = 'example.com'"
            ),
            {"a": test_agent, "d": day},
        ).fetchone()

        assert row is not None
        assert row[0] <= 86400, f"domain_usage.duration_seconds must be capped at 86400, got {row[0]}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
