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

"""
tests/test_report_job_email.py — Test suite for report email delivery.
Verifies dynamic report email content, clean email body presentation matching
client requirements, attachment descriptions, PDF failure fallback to HTML,
HTML escaping, and compatibility with existing callers.
"""

import os
import re
import smtplib
from datetime import datetime, date, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from engines.report_engine import (
    render_email_body_html,
    validate_attachments,
    describe_attachments,
    send_report_email,
    run_report_job,
)


# ==============================================================================
# 1. Correct report metadata in the email body
# ==============================================================================

def test_render_email_body_html_metadata_table():
    """Verify that report metadata is rendered properly in the email body."""
    html_out = render_email_body_html(
        report_title="Daily Agent Activity Report",
        report_type="daily",
        scope="individual",
        agent_name="Desktop-Agent-42",
        start_date="2026-10-12",
        end_date="2026-10-12",
        generated_at="2026-10-12 09:15:32 UTC",
    )

    # Check key metadata fields
    assert "Daily" in html_out
    assert "Individual" in html_out
    assert "Desktop-Agent-42" in html_out
    assert "2026-10-12" in html_out

    # Verify inline styling for email-client compatibility
    assert "font-family:" in html_out


def test_render_email_body_html_team_metadata_table():
    """Verify team-scoped metadata formatting with date ranges."""
    html_out = render_email_body_html(
        metadata={
            "report_title": "Weekly Team Performance Report",
            "report_type": "weekly",
            "scope": "team",
            "team_name": "Engineering Core",
            "start_date": "2026-10-05",
            "end_date": "2026-10-11",
            "generated_at_utc": "2026-10-12 08:00:00 UTC",
        }
    )

    assert "Weekly" in html_out
    assert "Team" in html_out
    assert "2026-10-05 to 2026-10-11" in html_out


# ==============================================================================
# 2. Support contact customization
# ==============================================================================

def test_no_unjustified_hardcoded_team_name():
    """Verify that support contact is configurable."""
    # 1. Rendered body with custom support contact
    rendered_custom = render_email_body_html(
        report_type="weekly",
        scope="team",
        support_contact="IT Operations Desk",
    )
    assert "IT Operations Desk" in rendered_custom

    # 2. Check template file exists
    tpl_file = Path(__file__).resolve().parent.parent / "server" / "templates" / "reports" / "email_body_template.html"
    assert tpl_file.exists()


# ==============================================================================
# 3. Attachment descriptions match actual MIME attachments
# ==============================================================================

def test_attachment_descriptions_both_pdf_and_html(tmp_path):
    """When both PDF and HTML are attached, the body mentions both and MIME has both."""
    pdf_file = tmp_path / "report.pdf"
    html_file = tmp_path / "report.html"
    pdf_file.write_bytes(b"%PDF-1.4 test")
    html_file.write_text("<html>report</html>", encoding="utf-8")

    attachments = [
        {"path": str(pdf_file), "filename": "report.pdf", "content_type": "application/pdf"},
        {"path": str(html_file), "filename": "report.html", "content_type": "text/html"},
    ]

    # Check rendered text
    body = render_email_body_html(
        report_type="weekly",
        scope="team",
        attachments=attachments,
    )
    assert "Both HTML and PDF versions are included for ease of review" in body

    # Send and check MIME parts
    mock_smtp = MagicMock()
    with patch("smtplib.SMTP", return_value=mock_smtp), \
         patch.dict(os.environ, {"SMTP_USER": "test@example.com", "SMTP_PASSWORD": "secret"}):
        ok, err = send_report_email(body, ["mgr@example.com"], "Test Both", attachments=attachments)
        assert ok is True

        raw_msg = mock_smtp.__enter__().sendmail.call_args[0][2]
        assert 'Content-Disposition: attachment; filename="report.pdf"' in raw_msg
        assert 'Content-Disposition: attachment; filename="report.html"' in raw_msg


def test_attachment_descriptions_pdf_only(tmp_path):
    """When only PDF is attached, the body mentions PDF only and MIME has PDF only."""
    pdf_file = tmp_path / "team_weekly.pdf"
    pdf_file.write_bytes(b"%PDF-1.4 pdf-only")

    attachments = [
        {"path": str(pdf_file), "filename": "team_weekly.pdf", "content_type": "application/pdf"}
    ]

    body = render_email_body_html(
        report_type="weekly",
        scope="team",
        attachments=attachments,
    )
    assert "A PDF version is included for ease of review" in body
    assert "Both" not in body

    mock_smtp = MagicMock()
    with patch("smtplib.SMTP", return_value=mock_smtp), \
         patch.dict(os.environ, {"SMTP_USER": "test@example.com", "SMTP_PASSWORD": "secret"}):
        ok, err = send_report_email(body, ["mgr@example.com"], "Test PDF Only", attachments=attachments)
        assert ok is True

        raw_msg = mock_smtp.__enter__().sendmail.call_args[0][2]
        assert 'Content-Disposition: attachment; filename="team_weekly.pdf"' in raw_msg
        assert 'Content-Disposition: attachment; filename="team_weekly.html"' not in raw_msg


def test_attachment_descriptions_html_only(tmp_path):
    """When only HTML is attached, the body mentions HTML only and MIME has HTML only."""
    html_file = tmp_path / "team_weekly.html"
    html_file.write_text("<html>html-only</html>", encoding="utf-8")

    attachments = [
        {"path": str(html_file), "filename": "team_weekly.html", "content_type": "text/html"}
    ]

    body = render_email_body_html(
        report_type="weekly",
        scope="team",
        attachments=attachments,
    )
    assert "An HTML version is included for ease of review" in body
    assert "Both" not in body

    mock_smtp = MagicMock()
    with patch("smtplib.SMTP", return_value=mock_smtp), \
         patch.dict(os.environ, {"SMTP_USER": "test@example.com", "SMTP_PASSWORD": "secret"}):
        ok, err = send_report_email(body, ["mgr@example.com"], "Test HTML Only", attachments=attachments)
        assert ok is True

        raw_msg = mock_smtp.__enter__().sendmail.call_args[0][2]
        assert 'Content-Disposition: attachment; filename="team_weekly.html"' in raw_msg
        assert 'Content-Disposition: attachment; filename="team_weekly.pdf"' not in raw_msg


# ==============================================================================
# 4. PDF generation failure fallback to HTML
# ==============================================================================

def test_pdf_generation_failure_with_successful_html_delivery(tmp_path):
    """When PDF generation fails, run_report_job falls back to HTML attachment and describes HTML only."""
    mock_db = MagicMock()
    mock_job = MagicMock()
    mock_job.status = "pending"
    mock_job.error_message = None
    mock_job.progress = {}
    mock_db.session.get.return_value = mock_job

    mock_send = MagicMock(return_value=(True, None))

    with patch("engines.report_engine.build_team_report", return_value={"_html": None}), \
         patch("engines.report_engine.render_report_html", return_value="<html>fallback report</html>"), \
         patch("engines.report_engine.generate_pdf", return_value=(False, "WeasyPrint not installed")), \
         patch("engines.report_engine.get_reports_storage_dir", return_value=tmp_path), \
         patch("engines.report_engine.send_report_email", mock_send):

        run_report_job(
            app=None,
            db=mock_db,
            job_id="job-fail-pdf",
            report_type="weekly",
            scope="team",
            agent_id=None,
            start_date=date(2026, 10, 5),
            end_date=date(2026, 10, 11),
            auto_email=True,
            recipients=["recipient@example.com"],
            include_pdf=True,
        )

        mock_send.assert_called_once()
        html_body_arg = mock_send.call_args[0][0]
        attachments_arg = mock_send.call_args[1].get("attachments")

        # Must describe HTML only (not PDF or both)
        assert "An HTML version is included for ease of review" in html_body_arg
        assert "Both" not in html_body_arg

        # Attachments list must contain the HTML file
        assert attachments_arg is not None
        assert len(attachments_arg) == 1
        assert attachments_arg[0]["filename"].endswith(".html")
        assert attachments_arg[0]["content_type"] == "text/html"


# ==============================================================================
# 5. Missing metadata and invalid attachment paths
# ==============================================================================

def test_missing_metadata_graceful_defaults():
    """Verify that missing metadata fields fall back gracefully without raising exceptions."""
    html_out = render_email_body_html(metadata={})
    assert "Activity Report" in html_out
    assert "N/A" in html_out


def test_invalid_attachment_paths_filtered_out(tmp_path):
    """Non-existent or 0-byte attachment files must be excluded and never described as attached."""
    ghost_pdf = tmp_path / "ghost.pdf"
    empty_html = tmp_path / "empty.html"
    empty_html.write_bytes(b"")  # 0 bytes

    attachments = [
        {"path": str(ghost_pdf), "filename": "ghost.pdf"},
        {"path": str(empty_html), "filename": "empty.html"},
    ]

    validated = validate_attachments(attachments)
    assert validated == []

    desc = describe_attachments(validated)
    assert desc["attachment_type"] == "none"
    assert "No report files are attached" in desc["description"]

    # Rendered email body must not claim files are attached
    rendered = render_email_body_html(attachments=attachments)
    assert "No report files are attached" in rendered
    assert "ghost.pdf" not in rendered


# ==============================================================================
# 6. HTML escaping
# ==============================================================================

def test_html_escaping_prevents_xss():
    """Dynamic strings containing HTML or script tags must be safely escaped."""
    xss_title = "<script>alert('title')</script>"
    xss_agent = "<img src=x onerror=alert('agent')>"
    xss_period = "<b onmouseover='alert(1)'>2026-10-12</b>"
    xss_contact = "<a href='javascript:void(0)'>support</a>"

    html_out = render_email_body_html(
        report_title=xss_title,
        report_type="daily",
        scope="individual",
        agent_name=xss_agent,
        period=xss_period,
        support_contact=xss_contact,
    )

    # Raw script or img tags must NOT exist
    assert "<script>alert('title')</script>" not in html_out
    assert "<img src=x onerror=alert('agent')>" not in html_out
    assert "<b onmouseover=" not in html_out
    assert "<a href='javascript:" not in html_out

    # Must be escaped entities
    assert "&lt;script&gt;alert(&#39;title&#39;)&lt;/script&gt;" in html_out or "&lt;script&gt;" in html_out
    assert "&lt;img src=x" in html_out


# ==============================================================================
# 7. Existing callers and retry behavior remain compatible
# ==============================================================================

def test_send_report_email_without_attachments_compatibility():
    """send_report_email without attachments preserves multipart/alternative behavior."""
    mock_smtp = MagicMock()
    with patch("smtplib.SMTP", return_value=mock_smtp), \
         patch.dict(os.environ, {"SMTP_USER": "test@example.com", "SMTP_PASSWORD": "secret"}):

        ok, err = send_report_email(
            html_content="<p>Legacy report body</p>",
            recipients=["user@example.com"],
            subject="Legacy Call",
            attachments=None,
        )

        assert ok is True
        raw_msg = mock_smtp.__enter__().sendmail.call_args[0][2]
        assert "multipart/alternative" in raw_msg
        assert "Content-Disposition: attachment" not in raw_msg
        import email, base64
        parsed = email.message_from_string(raw_msg)
        body_part = parsed.get_payload(0)
        decoded = base64.b64decode(body_part.get_payload()).decode("utf-8")
        assert "<p>Legacy report body</p>" in decoded


# ==============================================================================
# 8. No-attachment behavior follows the existing failure policy
# ==============================================================================

def test_send_report_email_all_invalid_attachments_aborts(tmp_path):
    """When attachments are specified but all are invalid, send_report_email fails without sending."""
    invalid_att = [{"path": str(tmp_path / "nonexistent.pdf"), "filename": "nonexistent.pdf"}]

    mock_smtp = MagicMock()
    with patch("smtplib.SMTP", return_value=mock_smtp), \
         patch.dict(os.environ, {"SMTP_USER": "test@example.com", "SMTP_PASSWORD": "secret"}):

        ok, err = send_report_email(
            html_content="<p>Content</p>",
            recipients=["user@example.com"],
            subject="Invalid Attachments",
            attachments=invalid_att,
        )

        assert ok is False
        assert "No valid attachments" in str(err)
        # Must not have contacted SMTP server or sent email
        mock_smtp.assert_not_called()


def test_weekly_cron_no_attachments_aborts():
    """weekly_cron send_email aborts if neither HTML nor PDF exists."""
    from weekly_cron.send_report_email import send_email

    # Pass non-existent paths
    res = send_email(
        html_file=None,
        pdf_file=None,
        start_date=date(2026, 10, 5),
        end_date=date(2026, 10, 11),
    )
    assert res is False
