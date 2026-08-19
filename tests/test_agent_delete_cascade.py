"""
Regression test for agent deletion failing on agent_current_status.

Reported from the dashboard:

    Failed to delete agent: Dependency rule on column 'agents.agent_id'
    tried to blank-out primary key column 'agent_current_status.agent_id'
    on instance '<AgentCurrentStatus at 0x...>'

agent_current_status.agent_id is BOTH that table's primary key and the
foreign key to agents.agent_id. Every other child of Agent declares
cascade="all, delete-orphan", but AgentCurrentStatus declared a bare
backref, so SQLAlchemy fell back to its default of nulling the child's FK
on parent delete. Because that column is the primary key it cannot be
nulled, so the ORM raised before Postgres' ON DELETE CASCADE could act -
making it impossible to delete any agent that had ever sent a heartbeat.
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


def _agent_with_status(hostname='delete-me'):
    """Create an agent that has a current_status row, as any agent that has
    sent a heartbeat will."""
    import server_models
    from extensions import db

    agent_id = uuid.uuid4()
    agent = server_models.Agent(agent_id=agent_id, hostname=hostname)
    db.session.add(agent)
    db.session.flush()

    status = server_models.AgentCurrentStatus(
        agent_id=agent_id,
        username='tester',
        current_app='pytest',
    )
    db.session.add(status)
    db.session.commit()
    return agent_id


class TestAgentDeleteCascade:

    def test_deleting_agent_with_current_status_succeeds(self, app):
        """The reported failure: this raised before the cascade was added."""
        import server_models
        from extensions import db

        with app.app_context():
            agent_id = _agent_with_status()

            agent = server_models.Agent.query.filter_by(agent_id=agent_id).first()
            assert agent is not None

            db.session.delete(agent)
            db.session.commit()   # raised "tried to blank-out primary key"

            assert server_models.Agent.query.filter_by(
                agent_id=agent_id).first() is None

    def test_current_status_row_is_removed_not_orphaned(self, app):
        """The child must be deleted, never left behind or nulled."""
        import server_models
        from extensions import db

        with app.app_context():
            agent_id = _agent_with_status('cascade-check')

            assert server_models.AgentCurrentStatus.query.filter_by(
                agent_id=agent_id).first() is not None

            db.session.delete(
                server_models.Agent.query.filter_by(agent_id=agent_id).first()
            )
            db.session.commit()

            assert server_models.AgentCurrentStatus.query.filter_by(
                agent_id=agent_id).first() is None, (
                "agent_current_status row outlived its agent"
            )

    def test_current_status_backref_is_scalar(self, app):
        """The model documents agent.current_status as one-to-one. Without
        uselist=False on the backref SQLAlchemy makes it a list."""
        import server_models

        with app.app_context():
            agent_id = _agent_with_status('scalar-check')
            agent = server_models.Agent.query.filter_by(agent_id=agent_id).first()

            assert not isinstance(agent.current_status, list), (
                "agent.current_status should be a scalar, got a list"
            )
            assert agent.current_status.current_app == 'pytest'

    def test_deleting_agent_without_status_still_works(self, app):
        """Agents that never sent a heartbeat must delete cleanly too."""
        import server_models
        from extensions import db

        with app.app_context():
            agent_id = uuid.uuid4()
            db.session.add(server_models.Agent(
                agent_id=agent_id, hostname='never-checked-in'))
            db.session.commit()

            db.session.delete(
                server_models.Agent.query.filter_by(agent_id=agent_id).first()
            )
            db.session.commit()

            assert server_models.Agent.query.filter_by(
                agent_id=agent_id).first() is None
