"""
Access control for the reporting engine (server_reports).

These endpoints were only @login_required, with no per-agent scoping, so any
logged-in non-admin could:
  - generate/queue a TEAM report covering every agent
  - generate/queue an INDIVIDUAL report for any agent_id they guessed
  - email a report to arbitrary recipients
  - read any job's result_html (the full rendered report) by job id
  - list every agent + Windows username via /reports/agents
"""

import os
import sys
import uuid
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))


@pytest.fixture
def app(monkeypatch):
    # monkeypatch, not os.environ[...] = ...: other suites (e.g.
    # test_midnight_span_handling) deliberately run against the real
    # DATABASE_URL, and permanently repointing it at in-memory SQLite
    # makes every later test fail with "no such table: agents".
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


def _make_user(role, linked_username=None):
    from auth import DashboardUser
    from extensions import db

    user = DashboardUser(
        username=f'{role}-{uuid.uuid4().hex[:6]}',
        role=role,
        linked_username=linked_username,
        is_active=True,
        session_version=1,
    )
    db.session.add(user)
    db.session.commit()
    return user


def _login(client, user):
    """
    Simulate a completed sign-in.

    Feature 037 / FR-002a: authentication is now bound to a tab, not just to the
    cookie, so login_required requires a live tab_session row as well as the
    session cookie. Issuing one here mirrors exactly what the real sign-in path
    does; without it every request in these tests is redirected to the sign-in
    page before reaching the authorization check under test.
    """
    from auth import issue_tab_session

    raw_token = issue_tab_session(user)
    with client.session_transaction() as sess:
        sess['user_id'] = user.id
        sess['username'] = user.username
        sess['session_version'] = user.session_version
        sess['tab_token'] = raw_token


DATES = {'start_date': '2026-07-01', 'end_date': '2026-07-07'}


def test_non_admin_cannot_generate_team_report(app):
    with app.app_context():
        user = _make_user('user', linked_username='jdoe')
        with app.test_client() as client:
            _login(client, user)
            resp = client.post('/dashboard/reports/generate',
                               json={'scope': 'team', **DATES})
    assert resp.status_code == 403


def test_non_admin_cannot_generate_report_for_foreign_agent(app):
    with app.app_context(), \
            patch('auth.can_view_agent', return_value=False):
        user = _make_user('user', linked_username='jdoe')
        with app.test_client() as client:
            _login(client, user)
            resp = client.post('/dashboard/reports/generate',
                               json={'scope': 'individual',
                                     'agent_id': str(uuid.uuid4()),
                                     **DATES})
    assert resp.status_code == 403


def test_non_admin_cannot_queue_team_report(app):
    with app.app_context():
        user = _make_user('user', linked_username='jdoe')
        with app.test_client() as client:
            _login(client, user)
            resp = client.post('/dashboard/reports/unified/generate',
                               json={'scope': 'team', **DATES})
    assert resp.status_code == 403


def test_non_admin_cannot_queue_report_for_foreign_agent(app):
    with app.app_context(), \
            patch('auth.can_view_agent', return_value=False):
        user = _make_user('user', linked_username='jdoe')
        with app.test_client() as client:
            _login(client, user)
            resp = client.post('/dashboard/reports/unified/generate',
                               json={'scope': 'individual',
                                     'agent_id': str(uuid.uuid4()),
                                     **DATES})
    assert resp.status_code == 403


def test_non_admin_cannot_email_reports(app):
    """Even for an agent they CAN see, emailing to arbitrary recipients is
    an admin action."""
    with app.app_context(), \
            patch('auth.can_view_agent', return_value=True):
        user = _make_user('user', linked_username='jdoe')
        with app.test_client() as client:
            _login(client, user)
            resp = client.post('/dashboard/reports/unified/generate',
                               json={'scope': 'individual',
                                     'agent_id': str(uuid.uuid4()),
                                     'auto_email': True,
                                     'recipients': ['attacker@example.com'],
                                     **DATES})
    assert resp.status_code == 403


def test_non_admin_cannot_read_another_users_job(app):
    from extensions import db
    from server_models import ReportGenerationJob
    from datetime import date

    with app.app_context():
        owner = _make_user('user', linked_username='owner')
        snooper = _make_user('user', linked_username='snooper')

        job_id = str(uuid.uuid4())
        db.session.add(ReportGenerationJob(
            id=job_id, report_type='weekly', scope='team',
            start_date=date(2026, 7, 1), end_date=date(2026, 7, 7),
            status='completed', created_by=owner.username,
            result_html='<h1>SECRET TEAM REPORT</h1>',
        ))
        db.session.commit()

        with app.test_client() as client:
            _login(client, snooper)
            resp = client.get(f'/dashboard/reports/unified/jobs/{job_id}')

    assert resp.status_code == 404
    assert b'SECRET' not in resp.data


def test_admin_can_read_any_job(app):
    from extensions import db
    from server_models import ReportGenerationJob
    from datetime import date

    with app.app_context():
        owner = _make_user('user', linked_username='owner')
        admin = _make_user('admin')

        job_id = str(uuid.uuid4())
        db.session.add(ReportGenerationJob(
            id=job_id, report_type='weekly', scope='team',
            start_date=date(2026, 7, 1), end_date=date(2026, 7, 7),
            status='completed', created_by=owner.username,
            result_html='<h1>REPORT</h1>',
        ))
        db.session.commit()

        with app.test_client() as client:
            _login(client, admin)
            resp = client.get(f'/dashboard/reports/unified/jobs/{job_id}')

    assert resp.status_code == 200


def test_non_admin_cannot_list_schedules(app):
    with app.app_context():
        user = _make_user('user', linked_username='jdoe')
        with app.test_client() as client:
            _login(client, user)
            resp = client.get('/dashboard/reports/schedules')
    # admin_required redirects non-admins away from the dashboard
    assert resp.status_code in (302, 403)
