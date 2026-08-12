"""
Tests for the dedup guard in server_updates.report_update_health().

report_health() on the agent side now retries on transport failures (see
test_updater_lifecycle.py::TestReportHealthRetry). If the server actually
committed the first attempt but the client never saw the acknowledgment
(e.g. connection reset after commit), the retry resends an identical
report. Without a dedup guard this would double-write UpdateHistory and
double-increment update_attempts. This file verifies the guard: a repeat
of the same (agent_id, version, status) within the dedup window is
acknowledged but not re-applied; a genuinely new report goes through
normally.

Calls the raw view function via __wrapped__ (bypassing @require_auth,
which isn't involved in the logic under test) inside a real Flask
request context, with server_models fully mocked - no real database
connection is made anywhere in this file.
"""

import sys
import types
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

sys.path.insert(0, __file__.rsplit('tests', 1)[0] + 'server')

import server_updates  # noqa: E402

_raw_report_update_health = server_updates.report_update_health.__wrapped__


@pytest.fixture
def app():
    application = Flask(__name__)
    application.register_blueprint(server_updates.updates_bp)
    return application


def _install_fake_server_models(last_history_row):
    fake_sm = types.ModuleType('server_models')
    fake_sm.UpdateHistory = MagicMock()
    fake_sm.UpdateHistory.query.filter_by.return_value.order_by.return_value.first.return_value = (
        last_history_row
    )
    return fake_sm


def _call(app, payload, fake_sm, fake_agent=None):
    fake_db = MagicMock()
    with patch.dict(sys.modules, {'server_models': fake_sm}), \
            patch.dict(sys.modules, {'extensions': types.ModuleType('extensions')}):
        sys.modules['extensions'].db = fake_db
        with patch.object(server_updates, '_get_agent_from_db', return_value=fake_agent), \
                patch.object(server_updates, '_log_update_event') as mock_log_event:
            with app.test_request_context(json=payload):
                resp = _raw_report_update_health()
    return resp, mock_log_event, fake_db


class TestDedupGuard:
    def test_duplicate_within_window_is_acknowledged_without_reapplying(self, app):
        recent = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=5)
        last_row = SimpleNamespace(to_version='4.2.1', status='success', created_at=recent)
        fake_sm = _install_fake_server_models(last_row)
        fake_agent = SimpleNamespace(
            update_status='downloading', target_version='4.2.1',
            update_attempts=0, last_update_error=None, version='4.1.0',
        )
        payload = {
            'agent_id': 'a1', 'version': '4.2.1',
            'previous_version': '4.1.0', 'status': 'healthy',
        }

        resp, mock_log_event, fake_db = _call(app, payload, fake_sm, fake_agent)

        assert resp.get_json()['acknowledged'] is True
        mock_log_event.assert_not_called()
        assert fake_agent.update_status == 'downloading', (
            "a duplicate must not re-mutate the already-correct agent record"
        )
        fake_db.session.commit.assert_not_called()

    def test_new_report_outside_window_is_applied_normally(self, app):
        old = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=10)
        last_row = SimpleNamespace(to_version='4.2.1', status='success', created_at=old)
        fake_sm = _install_fake_server_models(last_row)
        fake_agent = SimpleNamespace(
            update_status='installing', target_version='4.2.1',
            update_attempts=0, last_update_error=None, version='4.1.0',
        )
        payload = {
            'agent_id': 'a1', 'version': '4.2.1',
            'previous_version': '4.1.0', 'status': 'healthy',
        }

        resp, mock_log_event, fake_db = _call(app, payload, fake_sm, fake_agent)

        assert resp.get_json()['acknowledged'] is True
        mock_log_event.assert_called_once()
        assert fake_agent.update_status == 'up_to_date'
        fake_db.session.commit.assert_called_once()

    def test_different_status_is_not_treated_as_duplicate(self, app):
        recent = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=5)
        # Last recorded event was a failure; this new report is success -
        # must not be swallowed as a "duplicate".
        last_row = SimpleNamespace(to_version='4.2.1', status='failed', created_at=recent)
        fake_sm = _install_fake_server_models(last_row)
        fake_agent = SimpleNamespace(
            update_status='installing', target_version='4.2.1',
            update_attempts=1, last_update_error='previous failure', version='4.1.0',
        )
        payload = {
            'agent_id': 'a1', 'version': '4.2.1',
            'previous_version': '4.1.0', 'status': 'healthy',
        }

        resp, mock_log_event, fake_db = _call(app, payload, fake_sm, fake_agent)

        assert resp.get_json()['acknowledged'] is True
        mock_log_event.assert_called_once()
        assert fake_agent.update_status == 'up_to_date'
