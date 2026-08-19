"""Tests for report scheduling — BUG-001, BUG-003, BUG-015."""
import pytest
from datetime import datetime, timezone
import re
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
             patch("engines.report_engine.create_job", return_value="j1"), \
             patch("engines.report_engine.run_report_job") as mock_run, \
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
             patch("engines.report_engine.create_job", return_value="j2"), \
             patch("engines.report_engine.run_report_job"), \
             patch("server_reports._calc_next_run", side_effect=fake_calc):
            db.session.execute.return_value.fetchall.return_value = [_row(s)]
            run_scheduled_reports()
        assert captured.get("hour") == 14
        assert captured.get("dow") == 2


# ── T101 / D13 / FR-029, FR-030 — the new-schedule form starts empty ──────────

from pathlib import Path as _Path

REPORTS_TEMPLATE = (
    _Path(__file__).parent.parent / "server" / "templates" / "dashboard" / "reports.html"
)


def _reports_html():
    return REPORTS_TEMPLATE.read_text(encoding="utf-8")


class TestNewScheduleFormStartsEmpty:
    """
    D13: create a schedule, save it, delete it, then click New Schedule — the
    deleted schedule's values are pre-filled, so a user can unknowingly recreate
    the schedule they just removed.

    Root cause (T102): purely client-side DOM state. toggleNewScheduleForm()
    only flips `style.display`, and the save path calls it again to hide the
    form without ever clearing the inputs. The values therefore survive in the
    DOM and reappear when the form is next shown. It is *not* a server-side
    default — a hard refresh clears it, which is what distinguishes the two.

    Asserted against the template source: there is no JavaScript test runner in
    this repo, and the behaviour lives entirely in the page's inline script.
    """

    def test_a_reset_helper_exists(self):
        html = _reports_html()
        assert "resetScheduleForm" in html, (
            "no helper clears the schedule form, so values persist in the DOM "
            "between openings (D13, FR-029)"
        )

    def test_opening_the_form_clears_it(self):
        """
        FR-029: the form must be empty when opened for a *new* schedule.
        Clearing on open (rather than on close) also covers the case where the
        page was left with a half-filled form.
        """
        html = _reports_html()
        match = re.search(
            r"function\s+toggleNewScheduleForm\s*\([^)]*\)\s*\{(.*?)\n    \}",
            html,
            re.S,
        )
        assert match, "toggleNewScheduleForm is no longer present"
        assert "resetScheduleForm" in match.group(1), (
            "opening the new-schedule form does not clear it (D13, FR-029)"
        )

    @pytest.mark.parametrize(
        "field",
        ["sch-name", "sch-recipients", "sch-type", "sch-scope", "sch-freq", "sch-hour"],
    )
    def test_every_field_is_reset(self, field):
        html = _reports_html()
        match = re.search(r"function\s+resetScheduleForm\s*\([^)]*\)\s*\{(.*?)\n    \}", html, re.S)
        assert match, "resetScheduleForm is not defined"
        assert field in match.group(1), (
            f"{field} is not cleared when the form is reset, so its previous "
            f"value carries over (D13, FR-029)"
        )

    def test_agent_selection_is_cleared(self):
        """
        The agent picker is the field most likely to silently recreate a
        deleted schedule against the wrong machine.
        """
        html = _reports_html()
        match = re.search(r"function\s+resetScheduleForm\s*\([^)]*\)\s*\{(.*?)\n    \}", html, re.S)
        assert "sch-agent" in match.group(1), "the agent selection is not cleared (D13)"
