"""Tests for report scheduling — BUG-001, BUG-003, BUG-015."""
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch


def _row(mapping):
    r = MagicMock()
    r._mapping = mapping
    return r


SCHEDULE = {
    "id": 1, "report_type": "weekly", "scope": "team", "agent_id": None,
    "recipients": '["mgr@example.com"]', "frequency": "weekly",
    "day_of_week": 0, "day_of_month": None, "send_hour": 9,
    "auto_email": True, "include_pdf": False,
}


class TestRunScheduledReports:
    def test_passes_report_type_and_scope(self):
        """BUG-001: must pass report_type and scope from DB row, not None."""
        from background_tasks import run_scheduled_reports
        with patch("extensions.db") as db, \
             patch("report_engine.create_job", return_value="j1"), \
             patch("report_engine.run_report_job") as mock_run, \
             patch("server_reports._calc_next_run", return_value=datetime(2026,6,2,9,0,tzinfo=timezone.utc)):
            db.session.execute.return_value.fetchall.return_value = [_row(SCHEDULE)]
            run_scheduled_reports()
        mock_run.assert_called_once()
        args = mock_run.call_args[0]
        assert "weekly" in args and "team" in args

    def test_next_run_uses_stored_send_hour(self):
        """BUG-003: _calc_next_run must receive stored send_hour/day_of_week, not hardcoded None/9."""
        from background_tasks import run_scheduled_reports
        captured = {}
        def fake_calc(freq, dow, dom, hour):
            captured.update({"dow": dow, "hour": hour})
            return datetime(2026,6,4,14,0,tzinfo=timezone.utc)
        s = {**SCHEDULE, "send_hour": 14, "day_of_week": 2}
        with patch("extensions.db") as db, \
             patch("report_engine.create_job", return_value="j2"), \
             patch("report_engine.run_report_job"), \
             patch("server_reports._calc_next_run", side_effect=fake_calc):
            db.session.execute.return_value.fetchall.return_value = [_row(s)]
            run_scheduled_reports()
        assert captured.get("hour") == 14
        assert captured.get("dow") == 2
