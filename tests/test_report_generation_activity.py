"""
T014-T016, T018-T019 / D12 / FR-020, FR-021, FR-022 — report generation.

QA repro: Reports -> Activity Report -> scope Individual Agent -> select one
agent -> set start and end date -> Generate Report. Actual: not able to generate.

## Root cause (T013, fixed in T017)

Report templates were hardened for CSP and call `csp_nonce()` on their inline
<style>/<script> tags. In a request that global comes from a Flask context
processor, but reports render for email and PDF *outside* any request, where the
global does not exist — so every render raised UndefinedError. The failure was
total and hit all five templates. An empty nonce is the correct value for a
standalone document, which is what report output is.

## What these tests cover

The fix above restored generation. What remained was the *reporting of failure*:
`run_report_job` collapsed every unsuccessful outcome into a single message,
"No data found for the selected period", regardless of cause. An agent that does
not exist and an agent with a quiet week produced identical text, so a user
could not tell a mistake from an empty week.

  FR-021  a specific stated reason, never a generic failure
  FR-022  an empty range produces an empty-state report, NOT an error
"""
from datetime import date

import pytest

from engines import report_engine
from engines.report_engine import (
    REASON_AGENT_NOT_FOUND,
    REASON_NO_DATA,
    build_individual_report,
)


class _FakeDb:
    """Minimal stand-in: report_engine reaches the database only via _query."""

    def __init__(self, agent_rows=None, screen_time=None):
        self._agent_rows = agent_rows
        self._screen_time = screen_time or []


@pytest.fixture
def no_agent(monkeypatch):
    monkeypatch.setattr(report_engine, "_get_agent_info", lambda db, aid: {})


@pytest.fixture
def agent_with_no_activity(monkeypatch):
    monkeypatch.setattr(
        report_engine,
        "_get_agent_info",
        lambda db, aid: {
            "agent_id": "agent-1",
            "agent_name": "PC-QUIET",
            "hostname": "PC-QUIET",
            "os": "Windows 11",
            "username": "alice",
        },
    )
    for fn in ("_get_screen_time", "_get_app_usage", "_get_domain_usage",
               "_get_inventory_changes"):
        monkeypatch.setattr(report_engine, fn, lambda db, aid, s, e: [])


class TestAgentNotFound:
    """FR-021: a missing agent is a distinct, stated reason."""

    def test_returns_none_for_unknown_agent(self, no_agent):
        ctx = build_individual_report(_FakeDb(), "nope", date(2026, 1, 1), date(2026, 1, 7))
        assert ctx is None

    def test_reason_is_specific(self):
        assert REASON_AGENT_NOT_FOUND != REASON_NO_DATA, (
            "a missing agent and an empty date range report the same reason, so "
            "a user cannot tell a mistake from a quiet week (FR-021)"
        )

    def test_reason_names_the_agent_problem(self):
        assert "agent" in REASON_AGENT_NOT_FOUND.lower()


class TestEmptyRangeProducesAReport:
    """
    FR-022: an empty range is an empty-state report, not an error. A quiet week
    is a legitimate answer to the question the user asked.
    """

    def test_context_is_built_for_an_agent_with_no_activity(self, agent_with_no_activity):
        ctx = build_individual_report(_FakeDb(), "agent-1", date(2026, 1, 1), date(2026, 1, 7))
        assert ctx is not None, (
            "an agent with no activity in range produced no report at all; an "
            "empty week must render an empty-state report (FR-022)"
        )

    def test_empty_context_still_identifies_the_agent(self, agent_with_no_activity):
        """The report must still say whose quiet week it describes (FR-023)."""
        ctx = build_individual_report(_FakeDb(), "agent-1", date(2026, 1, 1), date(2026, 1, 7))
        assert ctx["agent_info"]["agent_name"] == "PC-QUIET"
        assert ctx["agent_info"]["agent_id"] == "agent-1"

    def test_empty_context_has_zeroed_totals_not_missing_keys(self, agent_with_no_activity):
        """
        The template renders these unconditionally; absent keys would turn an
        empty week back into a render error.
        """
        ctx = build_individual_report(_FakeDb(), "agent-1", date(2026, 1, 1), date(2026, 1, 7))
        assert ctx["screen_time"]["total_active"] == 0
        assert ctx["screen_time"]["days_worked"] == 0
        assert ctx["apps"] == []
        assert ctx["domains"] == []

    def test_empty_context_renders_without_error(self, agent_with_no_activity):
        """End to end: an empty week must produce HTML, not an exception."""
        ctx = build_individual_report(_FakeDb(), "agent-1", date(2026, 1, 1), date(2026, 1, 7))
        html = report_engine.render_report_html("weekly", "individual", ctx)
        assert "PC-QUIET" in html


class TestFailureReasonsAreDistinct:
    """FR-021, asserted against the job runner's source."""

    def _source(self):
        from pathlib import Path

        return (
            Path(__file__).parent.parent / "server" / "engines" / "report_engine.py"
        ).read_text(encoding="utf-8")

    def test_job_runner_does_not_use_one_generic_message(self):
        src = self._source()
        assert "fail_job(db, job_id, 'No data found for the selected period')" not in src, (
            "every unsuccessful outcome still collapses into one generic "
            "message (FR-021)"
        )

    def test_job_runner_reports_the_specific_reason(self):
        src = self._source()
        assert "REASON_AGENT_NOT_FOUND" in src, (
            "the job runner does not distinguish a missing agent (FR-021)"
        )
