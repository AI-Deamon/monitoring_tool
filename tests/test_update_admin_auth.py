"""
Authorization tests for the admin-only auto-update endpoints.

Regression guard: PUT /policy, POST /trigger-check and POST /clear-failure
were documented "Admin-only" but only checked for `user_id in session` — so
any logged-in non-admin user could disable auto-update, retarget the whole
fleet to another version, or force update checks. The checks were also
wrapped in try/except: pass, which skipped authorization entirely if the
import raised (fail-open).
"""

import os
import uuid

import pytest


ADMIN_ENDPOINTS = [
    ('put', '/api/v1/updates/policy', {'auto_update_enabled': False}),
    ('post', '/api/v1/updates/trigger-check', {'all': True}),
    ('post', f'/api/v1/updates/clear-failure/{uuid.uuid4()}', {}),
]


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


def _make_user(role):
    from auth import DashboardUser
    from extensions import db

    user = DashboardUser(
        username=f'{role}-{uuid.uuid4().hex[:6]}',
        role=role,
        is_active=True,
        session_version=1,
    )
    db.session.add(user)
    db.session.commit()
    return user


def _login(client, user):
    with client.session_transaction() as sess:
        sess['user_id'] = user.id
        sess['session_version'] = user.session_version


@pytest.mark.parametrize('method,path,payload', ADMIN_ENDPOINTS)
def test_anonymous_is_rejected(app, method, path, payload):
    with app.test_client() as client:
        resp = getattr(client, method)(path, json=payload)
    assert resp.status_code == 401


@pytest.mark.parametrize('method,path,payload', ADMIN_ENDPOINTS)
def test_non_admin_user_is_rejected(app, method, path, payload):
    with app.app_context():
        user = _make_user('user')
        with app.test_client() as client:
            _login(client, user)
            resp = getattr(client, method)(path, json=payload)
    assert resp.status_code == 403, (
        f"{method.upper()} {path} allowed a non-admin user "
        f"(status={resp.status_code})"
    )


@pytest.mark.parametrize('method,path,payload', ADMIN_ENDPOINTS)
def test_stale_session_is_rejected(app, method, path, payload):
    """A password change bumps session_version; old sessions must not pass."""
    with app.app_context():
        admin = _make_user('admin')
        with app.test_client() as client:
            _login(client, admin)
            admin.session_version = 2  # simulate password change
            from extensions import db
            db.session.commit()
            resp = getattr(client, method)(path, json=payload)
    assert resp.status_code == 401


def test_admin_can_update_policy(app):
    with app.app_context():
        admin = _make_user('admin')
        with app.test_client() as client:
            _login(client, admin)
            resp = client.put('/api/v1/updates/policy',
                              json={'auto_update_enabled': False})
    assert resp.status_code == 200
    assert resp.get_json()['auto_update_enabled'] is False
