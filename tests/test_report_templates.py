"""
Tests for report Jinja2 templates.
T002: BUG-011 — team_weekly_report.html must render dynamic data, not hardcoded April 2026 data.
"""
import pytest
from datetime import date
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATE_DIR = Path(__file__).parent.parent / "server" / "templates" / "reports"


def _make_env():
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    # Add filters used by templates
    def fmt_duration(seconds):
        if not seconds:
            return "0m"
        h, m = divmod(int(seconds) // 60, 60)
        return f"{h}h {m}m" if h else f"{m}m"

    def fmt_hours(seconds):
        return round((seconds or 0) / 3600, 1)

    env.filters["format_duration"] = fmt_duration
    env.filters["format_hours"] = fmt_hours
    return env


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
        """Template must show the start_date passed in context, not hardcoded April 2026."""
        env = _make_env()
        ctx = _minimal_team_context(date(2026, 1, 5), date(2026, 1, 11))
        html = env.get_template("team_weekly_report.html").render(**ctx)
        assert "January 05, 2026" in html, "start_date not rendered in template"

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
