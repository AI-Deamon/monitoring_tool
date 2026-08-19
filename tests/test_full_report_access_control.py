"""
Tests for api_agent_full_report access control (FR-006).
"""
import sys, os, pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'monitoring_tool', 'server'))
os.environ.setdefault('DATABASE_URL', 'sqlite:///:memory:')
os.environ.setdefault('SECRET_KEY', 'test-secret')


@pytest.fixture
def app():
    from server_app import create_app
    app = create_app()
    app.config['TESTING'] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def _mock_user(role='user'):
    u = MagicMock()
    u.id = 42
    u.role = role
    u.linked_username = 'other_user'
    u.session_version = 1
    u.is_active = True
    # Feature 037 / FR-006f: login_required redirects to the change-password
    # page while this flag is set. A MagicMock auto-creates every attribute as a
    # truthy object, so without setting it explicitly every request here would
    # be redirected (302) before reaching the access-control check under test
    # (403). Set it False so these tests exercise authorization, not rotation.
    u.must_change_password = False
    return u


def _valid_tab_session():
    """
    A live tab session, for tests that mock the database.

    Feature 037 / FR-002a: login_required now requires a valid tab_session row
    as well as the session cookie. These tests mock DashboardUser.query, so
    TabSession.query has nothing behind it either — without this the request is
    redirected (302) before the authorization check under test can return 403.
    """
    tab = MagicMock()
    tab.expiry_reason.return_value = None
    tab.revoked_at = None
    return tab


def test_full_report_returns_403_for_foreign_agent(client):
    """FR-006: non-admin gets 403 for an agent they are not linked to."""
    mock_user = _mock_user()
    mock_agent = MagicMock()
    mock_agent.agent_id = 'aaaaaaaa-0000-0000-0000-000000000001'
    mock_agent.last_seen = None

    with client.session_transaction() as sess:
        sess['user_id'] = 42
        sess['session_version'] = 1

    with patch('auth.DashboardUser') as mock_du, \
         patch('auth.lookup_tab_session', return_value=_valid_tab_session()), \
         patch('server_dashboard.can_view_agent', return_value=False), \
         patch('server_dashboard.server_models') as mock_models:

        mock_du.query.filter_by.return_value.first.return_value = mock_user
        mock_models.Agent.query.filter_by.return_value.first.return_value = mock_agent

        resp = client.get('/dashboard/api/agent/aaaaaaaa-0000-0000-0000-000000000001/full-report')

    assert resp.status_code == 403
    assert 'error' in (resp.get_json() or {})


def test_full_report_allows_linked_agent(client):
    """FR-006: can_view_agent=True must not block the response."""
    mock_user = _mock_user()
    mock_agent = MagicMock()
    mock_agent.agent_id = 'aaaaaaaa-0000-0000-0000-000000000002'
    mock_agent.last_seen = None

    with client.session_transaction() as sess:
        sess['user_id'] = 42
        sess['session_version'] = 1

    with patch('auth.DashboardUser') as mock_du, \
         patch('auth.lookup_tab_session', return_value=_valid_tab_session()), \
         patch('server_dashboard.can_view_agent', return_value=True), \
         patch('server_dashboard.server_models') as mock_models, \
         patch('server_dashboard._compute_core_hours_utilization', return_value={
             'productive_pct': 0, 'away_pct': 0, 'locked_pct': 0, 'idle_pct': 0,
             'productive_time_str': '0m', 'away_time_str': '0m',
             'locked_time_str': '0m', 'idle_time_str': '0m',
             'available_seconds': 0, 'locked_ch': 0, 'away_ch': 0,
             'utilization_percent': 0,
         }):

        mock_du.query.filter_by.return_value.first.return_value = mock_user
        mock_models.Agent.query.filter_by.return_value.first.return_value = mock_agent
        for attr in ['AgentCurrentStatus', 'ScreenTime']:
            getattr(mock_models, attr).query.filter_by.return_value.first.return_value = None
        for attr in ['AppSession', 'DomainVisit', 'ScreenTimeSpan']:
            getattr(mock_models, attr).query.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
        mock_models.AppSession.query.filter.return_value.order_by.return_value.first.return_value = None
        mock_models.AppUsage.query.filter_by.return_value.order_by.return_value.all.return_value = []
        mock_models.DomainUsage.query.filter_by.return_value.order_by.return_value.all.return_value = []

        resp = client.get('/dashboard/api/agent/aaaaaaaa-0000-0000-0000-000000000002/full-report')

    assert resp.status_code != 403
