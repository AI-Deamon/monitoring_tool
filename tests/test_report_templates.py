"""
Tests for report Jinja2 templates.
T002: BUG-011 — team_weekly_report.html must render dynamic data, not hardcoded April 2026 data.
"""
import pytest
from datetime import date
from pathlib import Path

from report_engine import _make_jinja_env

TEMPLATE_DIR = Path(__file__).parent.parent / "server" / "templates" / "reports"


def _make_env():
    """
    Use the production Jinja environment rather than a replica.

    This previously built its own Environment duplicating report_engine's setup.
    The copy drifted: CSP hardening added csp_nonce() to every report template,
    production registered the global but this replica did not, so the tests
    failed against an environment that no longer matched what ships. Importing
    the real factory means the tests exercise production behaviour and cannot
    drift from it again.
    """
    return _make_jinja_env()


def _minimal_team_context(start_date, end_date):
    """Minimal valid context for team weekly/monthly templates."""
    return {
        "start_date": start_date,
        "end_date": end_date,
        "generated_at": __import__("datetime").datetime(2026, 1, 12, 9, 0),
        "active_members": 2,
        "total_team_hours": "10.0",
        "avg_per_member": "5.0",
        "team_members": [
            {
                "username": "alice",
                "agent_info": {"hostname": "PC-ALICE", "os": "Windows 11"},
                "screen_time": {
                    "total_active": 18000,
                    "days_worked": 5,
                    "avg_daily": 3600,
                    "daily_breakdown": [],
                },
                "apps": [],
                "domains": [],
            }
        ],
        "top_team_apps": [],
        "top_team_domains": [],
        "daily_totals": [
            {"day": "Monday", "date": "2026-01-05", "active": 18000, "idle": 1800, "locked": 3600},
        ],
    }


class TestTeamWeeklyTemplate:
    """BUG-011: team_weekly_report.html must be a Jinja2 template, not hardcoded HTML."""

    def test_renders_passed_start_date(self):
        """
        Template must show the start_date passed in context, not hardcoded April 2026.

        Expected output updated for feature 037 / FR-007: reports previously
        rendered '%B %d, %Y' ("January 05, 2026"). The canonical product-wide
        format is now DD-MM-YYYY, so the same context renders "05-01-2026".
        The original intent of this test — that the date comes from context and
        is not hardcoded — is unchanged and still asserted.
        """
        env = _make_env()
        ctx = _minimal_team_context(date(2026, 1, 5), date(2026, 1, 11))
        html = env.get_template("team_weekly_report.html").render(**ctx)
        assert "05-01-2026" in html, "start_date not rendered in template"
        assert "January 05, 2026" not in html, "template still uses the pre-FR-007 format"

    def test_does_not_contain_hardcoded_april_date(self):
        """Template must NOT contain the hardcoded April 20, 2026 date."""
        env = _make_env()
        ctx = _minimal_team_context(date(2026, 1, 5), date(2026, 1, 11))
        html = env.get_template("team_weekly_report.html").render(**ctx)
        assert "April 20, 2026" not in html, "Template still contains hardcoded April 2026 data"

    def test_renders_active_members_count(self):
        """Template must render the active_members count from context."""
        env = _make_env()
        ctx = _minimal_team_context(date(2026, 3, 2), date(2026, 3, 8))
        html = env.get_template("team_weekly_report.html").render(**ctx)
        assert "2" in html  # active_members = 2

    def test_renders_member_username(self):
        """Template must render team member usernames from context."""
        env = _make_env()
        ctx = _minimal_team_context(date(2026, 3, 2), date(2026, 3, 8))
        html = env.get_template("team_weekly_report.html").render(**ctx)
        assert "alice" in html


# ── T058 / D16 / FR-023 — agent identity in every generated report ───────────

AGENT_NAME = "LAPTOP-QA-07"
AGENT_ID = "b3f1c2d4-5e6a-7b8c-9d0e-1f2a3b4c5d6e"

INDIVIDUAL_TEMPLATES = [
    "individual_weekly_report.html",
    "individual_monthly_report.html",
]
TEAM_TEMPLATES = [
    "team_weekly_report.html",
    "team_monthly_report.html",
    "team_weekly_report_pdf.html",
]


def _agent_info(name=AGENT_NAME, agent_id=AGENT_ID):
    """agent_info as build_individual_report supplies it (report_engine._get_agent_info)."""
    return {
        "agent_id": agent_id,
        "agent_name": name,
        "hostname": "PC-ALICE",
        "os": "Windows 11",
        "username": "alice",
    }


def _minimal_individual_context(start_date, end_date):
    """Minimal valid context for the individual weekly/monthly templates."""
    return {
        "agent_info": _agent_info(),
        "username": "alice",
        "start_date": start_date,
        "end_date": end_date,
        "generated_at": __import__("datetime").datetime(2026, 1, 12, 9, 0),
        "screen_time": {
            "total_active": 18000,
            "total_idle": 1800,
            "total_locked": 3600,
            "total_away": 0,
            "total": 23400,
            "days_worked": 5,
            "avg_daily": 3600,
            "daily_breakdown": [],
        },
        "apps": [],
        "domains": [],
        "new_installs": [],
        "uninstalls": [],
        "highest_day": None,
        "lowest_day": None,
    }


class TestReportAgentIdentity:
    """
    D16: "In the downloaded report agent name or id is not displaying."
    FR-023: every generated report MUST identify the agent(s) it describes by
    human-readable name AND by identifier.

    Before the fix, `agent_name` and `agent_id` appear zero times across all five
    report templates — individual reports render only username/hostname/os, and
    team reports render only username. A report with no agent identity on it is
    unusable as evidence however correct its contents are.
    """

    @pytest.mark.parametrize("template", INDIVIDUAL_TEMPLATES)
    def test_individual_report_shows_agent_name(self, template):
        env = _make_env()
        ctx = _minimal_individual_context(date(2026, 1, 5), date(2026, 1, 11))
        html = env.get_template(template).render(**ctx)
        assert AGENT_NAME in html, f"{template} does not render agent_name (D16, FR-023)"

    @pytest.mark.parametrize("template", INDIVIDUAL_TEMPLATES)
    def test_individual_report_shows_agent_id(self, template):
        env = _make_env()
        ctx = _minimal_individual_context(date(2026, 1, 5), date(2026, 1, 11))
        html = env.get_template(template).render(**ctx)
        assert AGENT_ID in html, f"{template} does not render agent_id (D16, FR-023)"

    @pytest.mark.parametrize("template", TEAM_TEMPLATES)
    def test_team_report_attributes_each_member(self, template):
        """
        FR-023 acceptance scenario 3: a report covering multiple agents must
        attribute each section to the correct agent — so per-member identity,
        not one identity for the whole document.
        """
        env = _make_env()
        ctx = _minimal_team_context(date(2026, 1, 5), date(2026, 1, 11))
        ctx["team_members"][0]["agent_info"] = _agent_info()
        html = env.get_template(template).render(**ctx)
        assert AGENT_NAME in html, f"{template} does not attribute its member by agent_name (D16, FR-023)"

    def test_falls_back_to_identifier_when_name_missing(self):
        """
        FR-026: a stable identifier fallback when no friendly name is recorded.
        An unnamed agent must still be identifiable, never blank.
        """
        env = _make_env()
        ctx = _minimal_individual_context(date(2026, 1, 5), date(2026, 1, 11))
        ctx["agent_info"] = _agent_info(name="")
        html = env.get_template("individual_weekly_report.html").render(**ctx)
        assert AGENT_ID in html, "unnamed agent must still be identified by its id (FR-026)"
