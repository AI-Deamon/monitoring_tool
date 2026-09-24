"""
Unit tests for report job email endpoint (/dashboard/reports/unified/jobs/<job_id>/email)
and HTML body / attachment formatting in send_report_email.
"""

import os
import sys
import uuid
import time
from datetime import date
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv('FLASK_ENV', 'development')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')
    monkeypatch.setenv('SECRET_KEY', 'test-secret-key-for-unit-tests')
    monkeypatch.setenv('SMTP_USER', 'test@example.com')
    monkeypatch.setenv('SMTP_PASSWORD', 'testpass')

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


def _make_admin(username='admin'):
    from auth import DashboardUser
    from werkzeug.security import generate_password_hash
    u = DashboardUser(
        username=username,
        password_hash=generate_password_hash('secret123'),
        role='admin',
        is_active=True,
        session_version=1,
    )
    return u


def _login(client, user):
    from auth import issue_tab_session
    raw_token = issue_tab_session(user)
    with client.session_transaction() as sess:
        sess['user_id'] = user.id
        sess['username'] = user.username
        sess['role'] = user.role
        sess['session_version'] = user.session_version
        sess['tab_token'] = raw_token


def test_email_job_result_launches_background_thread(app):
    from extensions import db
    from server_models import ReportGenerationJob

    with app.app_context():
        admin = _make_admin('admin_user')
        db.session.add(admin)

        job_id = str(uuid.uuid4())
        job = ReportGenerationJob(
            id=job_id,
            report_type='weekly',
            scope='team',
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 7),
            status='completed',
            created_by=admin.username,
            result_html='<html><body><h1>Weekly Team Report</h1></body></html>',
        )
        db.session.add(job)
        db.session.commit()

        mock_server = MagicMock()
        mock_server.__enter__.return_value = mock_server

        with patch('smtplib.SMTP', return_value=mock_server):
            with app.test_client() as client:
                _login(client, admin)
                resp = client.post(
                    f'/dashboard/reports/unified/jobs/{job_id}/email',
                    json={'recipients': ['team@example.com']}
                )

                assert resp.status_code == 200
                data = resp.get_json()
                assert data['success'] is True
                assert 'background' in data.get('message', '').lower()

                # Wait briefly for background thread execution
                time.sleep(0.5)

                assert mock_server.sendmail.called
                args = mock_server.sendmail.call_args[0]
                msg_str = args[2]

                # Verify email body text & HTML rendering
                assert 'Good Morning Team,' in msg_str
                assert '2026-09-01 to 2026-09-07' in msg_str
                assert 'Weekly Team Activity Report' in msg_str

                # Verify attachment presence
                assert 'team_weekly_2026-09-01_to_2026-09-07.html' in msg_str


def test_send_report_email_monthly_attachments(app, monkeypatch):
    monkeypatch.setenv('SMTP_USER', 'test@example.com')
    monkeypatch.setenv('SMTP_PASSWORD', 'testpass')

    from engines.report_engine import send_report_email

    mock_server = MagicMock()
    mock_server.__enter__.return_value = mock_server

    with patch('smtplib.SMTP', return_value=mock_server):
        ok, err = send_report_email(
            html_content='<html><body>Monthly Report</body></html>',
            recipients=['manager@example.com'],
            subject='Monthly Report Subject',
            report_type='monthly',
            scope='team',
            start_date='2026-08-01',
            end_date='2026-08-31'
        )

        assert ok is True
        assert err is None
        assert mock_server.sendmail.called
        msg_str = mock_server.sendmail.call_args[0][2]

        assert 'Monthly Team Activity Report' in msg_str
        assert '2026-08-01 to 2026-08-31' in msg_str
