"""
US3 — spans-authoritative elapsed days (reconcile-and-set + capability-gated
zeroing). DB-backed tests, run against the database configured in
server/.env (sentinel_test), exactly like test_midnight_span_handling.py.

Created rows are cleaned up via the agents FK cascade; test agents are
deleted explicitly in fixture teardown.
"""
import os
import re
import subprocess
import sys
import tempfile
import uuid
from datetime import date, datetime
from pathlib import Path

import pytest

# Ensure the DB target is the test database regardless of CWD (pytest may run
# from the repo root or from monitoring_tool/server; server/.env always wins,
# matching alembic env.py and server_config.py).
from dotenv import load_dotenv

_env = Path(__file__).parent.parent / "server" / ".env"
load_dotenv(_env, override=True)

API_KEY_PLAINTEXT = "pytest-span-authority-key"


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(scope="module")
def app_context():
    """Create Flask app context for server tests (mirrors
    test_midnight_span_handling.py)."""
    os.environ['FLASK_ENV'] = 'development'
    from server_app import create_app

    app = create_app()
    with app.app_context():
        yield app


@pytest.fixture
def test_agent(app_context):
    """Throwaway agent with a registered API key; FK cascade cleans telemetry
    rows, the fixture deletes the agent itself."""
    from extensions import db
    from sqlalchemy import text
    from server_auth import hash_api_key

    agent_id = str(uuid.uuid4())
    db.session.execute(
        text("INSERT INTO agents (agent_id, hostname, api_key) "
             "VALUES (:a, :h, :k)"),
        {'a': agent_id, 'h': 'pytest-span-authority',
         'k': hash_api_key(API_KEY_PLAINTEXT)},
    )
    db.session.commit()
    yield agent_id
    db.session.rollback()
    db.session.execute(text("DELETE FROM agents WHERE agent_id = :a"),
                       {'a': agent_id})
    db.session.commit()


# ============================================================================
# Helpers
# ============================================================================

def _insert_span(agent_id, state, start_iso, end_iso):
    """Insert a span with naive-UTC boundaries (as parse_agent_timestamp
    produces before the DB stores it)."""
    from extensions import db
    from sqlalchemy import text

    start = datetime.fromisoformat(start_iso)
    end = datetime.fromisoformat(end_iso)
    db.session.execute(
        text("""
            INSERT INTO screen_time_spans
                (span_id, agent_id, state, start_time, end_time, duration_seconds)
            VALUES (:sid, :a, :st, :start, :end, :dur)
        """),
        {
            'sid': f"{agent_id}-{state}-{uuid.uuid4().hex[:8]}",
            'a': agent_id,
            'st': state,
            'start': start,
            'end': end,
            'dur': int((end - start).total_seconds()),
        },
    )
    db.session.commit()


def _get_row(agent_id, day):
    """Return (date, active, idle, locked, away) or None."""
    from extensions import db
    from sqlalchemy import text

    return db.session.execute(
        text("SELECT date, active_seconds, idle_seconds, locked_seconds, "
             "COALESCE(away_seconds, 0) FROM screen_time "
             "WHERE agent_id = :a AND date = :d"),
        {'a': agent_id, 'd': day},
    ).fetchone()


def _run_reconcile(day):
    from extensions import db
    from sqlalchemy import text

    db.session.execute(text("SELECT sync_screen_time_from_spans(:d)"),
                       {'d': day})
    db.session.commit()


def _post_screentime(app, agent_id, payload):
    return app.test_client().post(
        '/api/v1/telemetry/screentime',
        headers={'X-Agent-ID': agent_id, 'X-API-Key': API_KEY_PLAINTEXT},
        json=payload,
    )


def _seed_row(agent_id, day, active, idle=0, locked=0, away=0):
    from extensions import db
    from sqlalchemy import text

    db.session.execute(
        text("""
            INSERT INTO screen_time
                (agent_id, date, active_seconds, idle_seconds, locked_seconds, away_seconds)
            VALUES (:a, :d, :act, :idl, :loc, :awy)
        """),
        {'a': agent_id, 'd': day, 'act': active, 'idl': idle,
         'loc': locked, 'awy': away},
    )
    db.session.commit()


# ============================================================================
# T023 — final-day report: totals NOT persisted; resolved day from spans
# ============================================================================

class TestFinalDayReport:
    def test_final_day_totals_not_persisted_row_equals_span_sums(
            self, app_context, test_agent):
        """US3-4: a final-day cumulative report with inflated totals must not
        overwrite the elapsed-day row; the resolved day (UTC_date(payload) - 1)
        is reconciled from spans."""
        day = date(2026, 7, 10)
        _insert_span(test_agent, 'active', '2026-07-10T09:00:00', '2026-07-10T11:00:00')
        _insert_span(test_agent, 'idle',   '2026-07-10T11:00:00', '2026-07-10T11:20:00')
        _insert_span(test_agent, 'locked', '2026-07-10T11:20:00', '2026-07-10T11:50:00')
        _insert_span(test_agent, 'away',   '2026-07-10T11:50:00', '2026-07-10T12:20:00')

        resp = _post_screentime(app_context, test_agent, {
            'active_seconds': 36000,   # fabricated/inflated cumulative total
            'idle_seconds': 0,
            'locked_seconds': 0,
            'away_seconds': 0,
            'current_state': 'active',
            'timestamp': '2026-07-11T06:00:00+05:30',  # 00:30Z Jul 11 -> resolved Jul 10
            'is_final_day': True,
            'final_day_date': '2026-07-10',
        })
        assert resp.status_code == 200, resp.get_json()
        assert resp.get_json()['status'] == 'success'

        row = _get_row(test_agent, day)
        assert row is not None
        assert (row[1], row[2], row[3], row[4]) == (7200, 1200, 1800, 1800)
        # The in-progress day must not be written by a final-day report.
        assert _get_row(test_agent, date(2026, 7, 11)) is None

    def test_final_day_inline_reconcile_failure_still_returns_200(
            self, app_context, test_agent, monkeypatch):
        """Clarification 2026-08-06 Q1: a failed inline reconcile logs ERROR
        and still returns 200 — accept-and-defer to the scheduled reconcile."""
        from extensions import db
        from sqlalchemy import text

        real_execute = db.session.execute

        def _boom(*args, **kwargs):
            raise RuntimeError("simulated reconcile failure")

        monkeypatch.setattr(db.session, "execute", _boom)
        try:
            resp = _post_screentime(app_context, test_agent, {
                'active_seconds': 1000,
                'idle_seconds': 0,
                'locked_seconds': 0,
                'away_seconds': 0,
                'current_state': 'active',
                'timestamp': '2026-07-11T06:00:00+05:30',
                'is_final_day': True,
            })
        finally:
            monkeypatch.setattr(db.session, "execute", real_execute)
        assert resp.status_code == 200
        assert resp.get_json()['status'] == 'success'


# ============================================================================
# T024 — reconcile-and-set: idempotent + corrects downward
# ============================================================================

class TestReconcile:
    def test_idempotent_and_corrects_downward(self, app_context, test_agent):
        """US3-1/2/3: the proc overwrites the row with the full span sum; a
        second run yields a byte-identical row; a previously-inflated row is
        corrected downward."""
        day = date(2026, 7, 9)
        _seed_row(test_agent, day, active=50000, idle=6000, locked=3000, away=1000)
        _insert_span(test_agent, 'active', '2026-07-09T09:00:00', '2026-07-09T10:00:00')

        _run_reconcile(day)

        row = _get_row(test_agent, day)
        assert (row[1], row[2], row[3], row[4]) == (3600, 0, 0, 0)

        _run_reconcile(day)
        assert tuple(_get_row(test_agent, day)) == tuple(row)

    def test_reconcile_reads_all_spans_including_processed(
            self, app_context, test_agent):
        """Late-arriving spans must count even though an earlier reconcile
        already marked that day's spans processed (FR-006: reconcile reads ALL
        spans for the day, not just unprocessed)."""
        from extensions import db
        from sqlalchemy import text

        day = date(2026, 7, 7)
        _insert_span(test_agent, 'active', '2026-07-07T09:00:00', '2026-07-07T10:00:00')

        _run_reconcile(day)
        assert _get_row(test_agent, day)[1] == 3600

        # Everything for the day is now processed.
        status = db.session.execute(
            text("SELECT count(*) FROM screen_time_spans "
                 "WHERE agent_id = :a AND start_time::DATE = :d AND NOT processed"),
            {'a': test_agent, 'd': day},
        ).scalar()
        assert status == 0

        # A late buffered span for the same elapsed day arrives.
        _insert_span(test_agent, 'active', '2026-07-07T10:00:00', '2026-07-07T10:30:00')

        _run_reconcile(day)
        assert _get_row(test_agent, day)[1] == 5400

    def test_cross_midnight_span_is_split_between_two_days(
            self, app_context, test_agent):
        """Agent state machine splits spans at midnight:
        Span 1: Aug 31, 23:00 -> Aug 31, 23:59:59 (3600s)
        Span 2: Sep 1,  00:00 -> Sep 1,  02:00:00 (7200s)
        """
        agent_id = test_agent

        # Span 1 (Aug 31 portion: 23:00 to 00:00 = 3600s)
        _insert_span(agent_id, 'active', '2026-08-31T23:00:00', '2026-09-01T00:00:00')

        # Span 2 (Sep 1 portion: 00:00 to 02:00 = 7200s)
        _insert_span(agent_id, 'active', '2026-09-01T00:00:00', '2026-09-01T02:00:00')

        # Reconcile both days
        _run_reconcile(date(2026, 8, 31))
        _run_reconcile(date(2026, 9, 1))

        aug31_row = _get_row(agent_id, date(2026, 8, 31))
        sep1_row = _get_row(agent_id, date(2026, 9, 1))

        assert aug31_row is not None
        assert sep1_row is not None

        # Check active_seconds for each day
        assert aug31_row[1] == 3600
        assert sep1_row[1] == 7200


# ============================================================================
# T025 — late span lands within one daily sweep cycle (SC-004)
# ============================================================================

class TestDailySweep:
    def test_late_span_reconciled_within_next_sweep_cycle(
            self, app_context, test_agent):
        from background_tasks import reconcile_elapsed_screentime_days

        day = date(2026, 7, 8)
        _insert_span(test_agent, 'active', '2026-07-08T09:00:00', '2026-07-08T10:00:00')
        _run_reconcile(day)
        assert _get_row(test_agent, day)[1] == 3600

        # Late buffered span for the same elapsed day.
        _insert_span(test_agent, 'active', '2026-07-08T10:00:00', '2026-07-08T10:30:00')

        # Next daily sweep, its UTC-day window advanced by 24h (reference date
        # = today). The last 7 elapsed UTC days are covered, so the past row
        # reconciles to include the late span within one cycle.
        reconcile_elapsed_screentime_days(reference_date=date(2026, 7, 10))
        assert _get_row(test_agent, day)[1] == 5400


# ============================================================================
# T026 — non-final cumulative report still updates the in-progress day
# ============================================================================

class TestNonFinalReport:
    def test_non_final_cumulative_updates_in_progress_day(
            self, app_context, test_agent):
        day = date(2026, 7, 11)
        resp = _post_screentime(app_context, test_agent, {
            'active_seconds': 2500,
            'idle_seconds': 300,
            'locked_seconds': 0,
            'away_seconds': 0,
            'current_state': 'active',
            'timestamp': '2026-07-11T10:00:00+05:30',
            'is_final_day': False,
        })
        assert resp.status_code == 200, resp.get_json()

        row = _get_row(test_agent, day)
        assert row is not None
        assert (row[1], row[2]) == (2500, 300)


# ============================================================================
# T027 — capability-gated zeroing; never create rows for agents with no data
# ============================================================================

class TestCapabilityGatedZeroing:
    def test_span_capable_agent_stale_row_zeroed(self, app_context, test_agent):
        from extensions import db
        from sqlalchemy import text

        # Capability: agent has produced at least one span historically.
        _insert_span(test_agent, 'active', '2026-07-07T09:00:00', '2026-07-07T10:00:00')
        stale_day = date(2026, 7, 8)
        _seed_row(test_agent, stale_day, active=4000, idle=500)

        _run_reconcile(stale_day)

        row = _get_row(test_agent, stale_day)
        assert (row[1], row[2], row[3], row[4]) == (0, 0, 0, 0)

        # The capability history row itself is untouched by a different day's
        # reconcile (the sweep only touches p_date).
        _cleanup = db.session  # noqa — keep flake8 quiet about unused import

    def test_no_row_created_for_agent_with_no_data(self, app_context, test_agent):
        from extensions import db
        from sqlalchemy import text

        no_data_agent = str(uuid.uuid4())
        db.session.execute(
            text("INSERT INTO agents (agent_id, hostname) VALUES (:a, :h)"),
            {'a': no_data_agent, 'h': 'pytest-no-data'},
        )
        db.session.commit()
        try:
            _run_reconcile(date(2026, 7, 8))
            assert _get_row(no_data_agent, date(2026, 7, 8)) is None
        finally:
            db.session.execute(
                text("DELETE FROM agents WHERE agent_id = :a"),
                {'a': no_data_agent},
            )
            db.session.commit()


# ============================================================================
# T028 — pre-span-era agent rows left untouched (FR-006 gate / US3-7)
# ============================================================================

class TestPreSpanEraAgent:
    def test_rows_untouched_when_agent_has_no_spans_ever(
            self, app_context, test_agent):
        """An agent that has never produced a span (pre-span-era build) must
        have its historical rows left untouched — never zeroed, never
        corrected."""
        _seed_row(test_agent, date(2026, 7, 5), active=5000)
        _seed_row(test_agent, date(2026, 7, 6), active=4000)

        _run_reconcile(date(2026, 7, 5))
        _run_reconcile(date(2026, 7, 6))

        assert _get_row(test_agent, date(2026, 7, 5))[1] == 5000
        assert _get_row(test_agent, date(2026, 7, 6))[1] == 4000

    def test_pre_upgrade_days_untouched_when_swept_after_first_span(
            self, app_context, test_agent):
        """Boundary case (review fix): the capability gate must be scoped to
        p_date, not "has this agent EVER sent a span, as of right now". An
        agent whose first-ever span lands on day X must not have its
        genuinely pre-upgrade rows (X-1..X-6) zeroed just because a later
        sweep run, evaluated after the upgrade, sees the agent as globally
        span-capable."""
        pre_upgrade_day = date(2026, 7, 20)
        upgrade_day = date(2026, 7, 21)
        _seed_row(test_agent, pre_upgrade_day, active=6000, idle=100)

        # Agent upgrades and sends its first-ever span on upgrade_day.
        _insert_span(test_agent, 'active', '2026-07-21T09:00:00', '2026-07-21T10:00:00')

        # A sweep later reconciles BOTH days (e.g. the 7-day catch-up window
        # spans the upgrade boundary). The pre-upgrade day has no spans of
        # its own and must be left untouched, not zeroed.
        _run_reconcile(pre_upgrade_day)
        _run_reconcile(upgrade_day)

        pre_row = _get_row(test_agent, pre_upgrade_day)
        assert (pre_row[1], pre_row[2]) == (6000, 100), (
            "pre-upgrade row was zeroed: the capability gate is not "
            "date-scoped to p_date"
        )
        assert _get_row(test_agent, upgrade_day)[1] == 3600


# ============================================================================
# T029 — alembic upgrade head completes clean on a fresh database (SC-005)
# ============================================================================

class TestFreshDatabaseMigration:
    def test_alembic_upgrade_head_on_fresh_database(self):
        """Run the full migration chain (up to and including our new proc
        redefinition) against a throwaway database."""
        import sqlalchemy

        url = os.environ['DATABASE_URL']
        m = re.match(
            r'postgresql(?:\+psycopg2)?://([^:]+):([^@]+)@([^:/]+):?(\d+)?/([^?]+)',
            url,
        )
        assert m, f"Cannot parse DATABASE_URL: {url!r}"
        user, pwd, host, port, _ = m.groups()
        port = port or '5432'

        tmp_db = f"sentinel_migtest_{uuid.uuid4().hex[:8]}"
        maint_url = f"postgresql://{user}:{pwd}@{host}:{port}/postgres"
        eng = sqlalchemy.create_engine(maint_url)
        try:
            with eng.connect() as conn:
                conn = conn.execution_options(isolation_level='AUTOCOMMIT')
                conn.execute(sqlalchemy.text(f'CREATE DATABASE "{tmp_db}"'))
        except Exception as e:  # noqa: BLE001
            pytest.skip(f"cannot create throwaway database: {e}")

        # env.py and server_config.py load server/.env with override=True, so a
        # plain DATABASE_URL env var is silently clobbered. Shadow .env with the
        # temp URL so the subprocess actually migrates the throwaway DB.
        env_file = Path(__file__).parent.parent / 'server' / '.env'
        if not env_file.exists():
            # CI sets DATABASE_URL directly and never checks out a .env file
            # (it's gitignored); this test only applies where one exists.
            pytest.skip("server/.env not present (expected in CI)")
        original_env = env_file.read_text(encoding='utf-8')
        tmp_url = f"postgresql://{user}:{pwd}@{host}:{port}/{tmp_db}"
        _out, _found = [], False
        for _line in original_env.splitlines():
            if _line.strip().startswith('DATABASE_URL='):
                _out.append(f'DATABASE_URL="{tmp_url}"')
                _found = True
            else:
                _out.append(_line)
        if not _found:
            _out.append(f'DATABASE_URL="{tmp_url}"')
        shadow_env = '\n'.join(_out) + '\n'

        try:
            env_file.write_text(shadow_env, encoding='utf-8')
            ini = str(Path(__file__).parent.parent / 'server' / 'alembic.ini')
            run_env = dict(os.environ, PYTHONIOENCODING='utf-8')
            with tempfile.TemporaryDirectory() as td:
                proc = subprocess.run(
                    [sys.executable, '-m', 'alembic', '-c', ini, 'upgrade', 'head'],
                    capture_output=True, text=True, env=run_env, cwd=td,
                )
            assert proc.returncode == 0, proc.stdout + proc.stderr

            # The new proc is installed and functional on the fresh DB.
            check_eng = sqlalchemy.create_engine(tmp_url)
            with check_eng.connect() as conn:
                proc_ver = conn.execute(sqlalchemy.text(
                    "SELECT proname FROM pg_proc WHERE proname = "
                    "'sync_screen_time_from_spans'"
                )).fetchone()
                assert proc_ver is not None
        finally:
            env_file.write_text(original_env, encoding='utf-8')
            with eng.connect() as conn:
                conn = conn.execution_options(isolation_level='AUTOCOMMIT')
                conn.execute(
                    sqlalchemy.text(f'DROP DATABASE IF EXISTS "{tmp_db}" WITH (FORCE)')
                )
