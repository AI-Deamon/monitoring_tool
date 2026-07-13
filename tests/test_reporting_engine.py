"""
Tests for report_engine.py and background_tasks.py scheduler.
TDD: These tests are written first and must FAIL before implementation.
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, call


class TestRunScheduledReports:
    """BUG-001: run_scheduled_reports() must fetch all schedule columns, not just id."""

    def test_passes_all_schedule_fields_to_run_report_job(self):
        """
        run_scheduled_reports() must pass report_type, scope, recipients, frequency,
        send_hour from the schedule row to run_report_job — not None values.
        """
        from background_tasks import run_scheduled_reports

        # Mock a due schedule row with all fields
        mock_row = MagicMock()
        mock_row._mapping = {
            "id": 1,
            "report_type": "weekly",
            "scope": "team",
            "agent_id": None,
            "recipients": '["manager@example.com"]',
            "frequency": "weekly",
            "day_of_week": 0,
            "day_of_month": None,
            "send_hour": 9,
            "auto_email": True,
            "include_pdf": False,
        }

        with patch("extensions.db") as mock_db, \
             patch("report_engine.create_job", return_value="job-123"), \
             patch("report_engine.run_report_job") as mock_run, \
             patch("server_reports._calc_next_run", return_value=datetime(2026, 6, 2, 9, 0, tzinfo=timezone.utc)):

            mock_db.session.execute.return_value.fetchall.return_value = [mock_row]

            run_scheduled_reports()

            # Must have been called with actual values, not None
            mock_run.assert_called_once()
            call_kwargs = mock_run.call_args
            # report_type and scope must be the real values
            assert "weekly" in str(call_kwargs), f"report_type 'weekly' not passed: {call_kwargs}"
            assert "team" in str(call_kwargs), f"scope 'team' not passed: {call_kwargs}"


class TestRunReportJobEmailFailure:
    """BUG-005: email failure must be stored in error_message, job stays 'completed'."""

    def test_email_failure_stored_in_error_message(self):
        """
        When auto_email=True and SMTP fails, job.status must remain 'completed'
        and job.error_message must contain 'email failed'.
        """
        from report_engine import run_report_job

        mock_db = MagicMock()
        mock_job = MagicMock()
        mock_job.status = "pending"
        mock_job.error_message = None
        mock_db.session.get.return_value = mock_job

        with patch("report_engine.build_team_report", return_value={"_html": None, "start_date": None, "end_date": None}), \
             patch("report_engine.build_individual_report", return_value=None), \
             patch("report_engine.render_report_html", return_value="<html>report</html>"), \
             patch("report_engine.update_job_progress"), \
             patch("report_engine.send_report_email", return_value=(False, "SMTP credentials not configured")):

            run_report_job(
                app=None, db=mock_db, job_id="job-1",
                report_type="weekly", scope="team",
                agent_id=None,
                start_date=__import__("datetime").date(2026, 1, 5),
                end_date=__import__("datetime").date(2026, 1, 11),
                auto_email=True,
                recipients=["manager@example.com"],
            )

        # Job must be completed (report generated), not failed
        assert mock_job.status == "completed", f"Expected 'completed', got '{mock_job.status}'"
        # Error message must mention email failure
        assert mock_job.error_message is not None, "error_message must be set on email failure"
        assert "email failed" in mock_job.error_message.lower(), \
            f"error_message must contain 'email failed': {mock_job.error_message}"


class TestCompleteJobTimezone:
    """BUG-006: complete_job() must store timezone-aware datetime in completed_at."""

    def test_completed_at_is_timezone_aware(self):
        """complete_job() must set completed_at to a timezone-aware UTC datetime."""
        from report_engine import complete_job

        mock_db = MagicMock()
        mock_job = MagicMock()
        mock_job.completed_at = None
        mock_db.session.get.return_value = mock_job

        complete_job(mock_db, "job-1", "<html>report</html>")

        assert mock_job.completed_at is not None, "completed_at must be set"
        assert mock_job.completed_at.tzinfo is not None, \
            "completed_at must be timezone-aware (not naive datetime)"
