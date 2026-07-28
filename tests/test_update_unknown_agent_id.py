"""
Regression test for the aborted-transaction bug on /api/v1/updates/latest.

Symptom observed in the production log: every update check made without an
X-Agent-ID header logged

    [UPDATES] DB lookup failed for unknown: (psycopg2.errors.
    InvalidTextRepresentation) invalid input syntax for type uuid: "unknown"

immediately followed by

    [UPDATES] Policy lookup error: (psycopg2.errors.InFailedSqlTransaction)
    current transaction is aborted, commands ignored until end of
    transaction block

Root cause: the /latest handler defaults agent_id to the literal string
'unknown' when the header is missing, and _get_agent_from_db() passed that
straight into a filter on agents.agent_id - a native UUID column. Postgres
rejects the cast and aborts the transaction, so every later query in the
same request fails too, including the global-policy lookup. The handler
swallowed both errors, so the update check silently returned no update
instead of telling the agent what to do.

A non-UUID agent id can never match a UUID column, so the query must not be
issued at all.
"""

import uuid

import pytest


@pytest.fixture
def app(monkeypatch):
    # monkeypatch, not os.environ[...] = ...: other suites (e.g.
    # test_midnight_span_handling) deliberately run against the real
    # DATABASE_URL, and permanently repointing it at in-memory SQLite makes
    # every later test fail with "no such table: agents".
    monkeypatch.setenv('FLASK_ENV', 'development')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')
    monkeypatch.setenv('SECRET_KEY', 'test-secret-key-for-unit-tests')

    from server_app import create_app
    from extensions import db

    app = create_app()
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['WTF_CSRF_ENABLED'] = False

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()


class TestNonUuidAgentIdDoesNotPoisonTheSession:

    def test_unknown_agent_id_issues_no_query(self, app):
        """The literal 'unknown' must miss without touching the DB."""
        import server_updates

        with app.app_context():
            import server_models

            calls = []
            original = server_models.Agent.query

            class _Tripwire:
                def filter_by(self, **kwargs):
                    calls.append(kwargs)
                    return original.filter_by(**kwargs)

            server_models.Agent.query = _Tripwire()
            try:
                assert server_updates._get_agent_from_db('unknown') is None
            finally:
                server_models.Agent.query = original

            assert calls == [], (
                f"a non-UUID id must not reach the database, but a query was "
                f"issued with {calls!r}"
            )

    @pytest.mark.parametrize(
        'bad_id',
        ['unknown', '', 'not-a-uuid', '12345', None, 42],
    )
    def test_bad_ids_return_none_without_raising(self, app, bad_id):
        import server_updates

        with app.app_context():
            assert server_updates._get_agent_from_db(bad_id) is None

    def test_real_uuid_still_resolves(self, app):
        """The happy path must keep working."""
        import server_updates
        import server_models
        from extensions import db

        agent_id = uuid.uuid4()
        with app.app_context():
            db.session.add(server_models.Agent(
                agent_id=agent_id,
                hostname='regression-host',
            ))
            db.session.commit()

            found = server_updates._get_agent_from_db(str(agent_id))
            assert found is not None
            assert found.hostname == 'regression-host'

    def test_policy_lookup_still_works_after_a_bad_id(self, app):
        """The session must stay usable - this is what actually broke."""
        import server_updates

        with app.app_context():
            assert server_updates._get_agent_from_db('unknown') is None

            # In the bug this returned None because the transaction was
            # already aborted by the query above.
            policy = server_updates._get_global_policy()
            assert policy is not None, (
                "global policy lookup failed after a non-UUID agent id - "
                "the DB session was left in an aborted state"
            )

    def test_latest_endpoint_without_agent_header(self, app):
        """End-to-end: a header-less update check must not 500."""
        client = app.test_client()
        response = client.get('/api/v1/updates/latest')
        assert response.status_code == 200
        assert response.get_json() is not None
