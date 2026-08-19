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
             patch("engines.report_engine.create_job", return_value="job-123"), \
             patch("engines.report_engine.run_report_job") as mock_run, \
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
        from engines.report_engine import run_report_job

        mock_db = MagicMock()
        mock_job = MagicMock()
        mock_job.status = "pending"
        mock_job.error_message = None
        mock_db.session.get.return_value = mock_job

        with patch("engines.report_engine.build_team_report", return_value={"_html": None, "start_date": None, "end_date": None}), \
             patch("engines.report_engine.build_individual_report", return_value=None), \
             patch("engines.report_engine.render_report_html", return_value="<html>report</html>"), \
             patch("engines.report_engine.update_job_progress"), \
             patch("engines.report_engine.send_report_email", return_value=(False, "SMTP credentials not configured")):

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
    """
    complete_job() must store NAIVE UTC in completed_at (D02 / FR-009).

    This previously asserted the opposite ("BUG-006: must be timezone-aware").
    That was the wrong layer. ReportGenerationJob.completed_at is
    `db.Column(db.DateTime)` — TIMESTAMP WITHOUT TIME ZONE — so an aware value
    is not stored as-is: psycopg2 sends the offset and Postgres casts
    timestamptz -> timestamp using the SESSION TimeZone, landing 5:30 ahead of
    UTC on an IST server. The same defect put update_history.started_at at
    16:35 for an instant its own created_at recorded as 11:05.

    The assertion passed only because the job is a MagicMock: it pinned the
    in-Python type and never observed what reached the database.

    The rest of the stack already assumes naive UTC — utils.datetime_format
    treats a stored naive value as UTC, and the dashboard parses these strings
    with DateFmt.parseStored() precisely because "naive ISO from the API is
    UTC" (templates/dashboard/updates.html). A column that genuinely wants an
    aware value declares it, as TabSession does with db.DateTime(timezone=True).
    """

    def test_completed_at_is_naive_utc(self):
        from datetime import datetime, timezone

        from engines.report_engine import complete_job

        mock_db = MagicMock()
        mock_job = MagicMock()
        mock_job.completed_at = None
        mock_db.session.get.return_value = mock_job

        complete_job(mock_db, "job-1", "<html>report</html>")

        assert mock_job.completed_at is not None, "completed_at must be set"
        assert mock_job.completed_at.tzinfo is None, (
            "completed_at must be NAIVE — an aware value is silently shifted by "
            "the session timezone when written to a TIMESTAMP WITHOUT TIME ZONE "
            "column"
        )
        # ...and naive means naive *UTC*, not local wall-clock.
        drift = abs(
            (mock_job.completed_at - datetime.now(timezone.utc).replace(tzinfo=None))
            .total_seconds()
        )
        assert drift < 5, f"completed_at is not UTC — drifted {drift}s"

    def test_fail_job_completed_at_is_naive_utc(self):
        """fail_job() shares the column and must match."""
        from engines.report_engine import fail_job

        mock_db = MagicMock()
        mock_job = MagicMock()
        mock_job.completed_at = None
        mock_db.session.get.return_value = mock_job

        fail_job(mock_db, "job-1", "boom")

        assert mock_job.completed_at is not None
        assert mock_job.completed_at.tzinfo is None
