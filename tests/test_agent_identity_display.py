"""
T070 / D21 / FR-026, FR-026a–d — agents identified wherever they appear.

QA reported two surfaces:

  (a) Login as admin -> Top Performance table.
      "agent name is not displaying fully"
      Cause: overview.js rendered `agent.hostname.substring(0, 8)` in all three
      leaderboards. A hard 8-character cut, with no ellipsis and no way to see
      the remainder — "LAPTOP-QA-07" displayed as "LAPTOP-Q". Two agents sharing
      an 8-character prefix rendered identically, which FR-026b forbids.

  (b) Login as admin -> Updates -> Update History.
      "Agent full name or id is not displaying (partial name is displaying)"
      Cause: updates.html rendered `${h.agent_id.slice(0, 8)}...` — the first
      eight characters of a UUID, with no human-readable name anywhere in the
      row. FR-026 requires a name, with the identifier as fallback, not instead.

There is no JavaScript test runner in this repo (all 39 existing test files are
pytest), so these assert the contract against the source, in the same way
test_report_print_layout.py asserts print CSS. The point is to pin the rules so
a hard truncation cannot silently return.
"""
import re
from pathlib import Path

import pytest

STATIC = Path(__file__).parent.parent / "server" / "static" / "js"
TEMPLATES = Path(__file__).parent.parent / "server" / "templates" / "dashboard"

OVERVIEW_JS = STATIC / "overview.js"
AGENT_DISPLAY_JS = STATIC / "agent_display.js"
UPDATES_HTML = TEMPLATES / "updates.html"
BASE_HTML = TEMPLATES / "base.html"


@pytest.fixture(scope="module")
def overview_js() -> str:
    return OVERVIEW_JS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def updates_html() -> str:
    return UPDATES_HTML.read_text(encoding="utf-8")


class TestSharedAgentFormatter:
    """
    FR-026a–d are one rule applied in several places. As with the date sweep,
    the fix is a shared helper rather than a per-screen patch — otherwise the
    next screen reintroduces the defect.
    """

    def test_shared_helper_exists(self):
        assert AGENT_DISPLAY_JS.exists(), (
            "no shared agent-display helper; each screen would truncate its own "
            "way and the defect returns on the next one (FR-026a)"
        )

    def test_helper_is_published_globally(self):
        src = AGENT_DISPLAY_JS.read_text(encoding="utf-8")
        assert "AgentFmt" in src, "the helper is not published for templates to use"

    def test_helper_is_loaded_for_every_dashboard_page(self):
        base = BASE_HTML.read_text(encoding="utf-8")
        assert "agent_display.js" in base, (
            "the shared helper is not loaded by base.html, so pages that need "
            "it would each have to remember to include it"
        )

    def test_helper_escapes_html(self):
        """Hostnames are agent-supplied and get interpolated into innerHTML."""
        src = AGENT_DISPLAY_JS.read_text(encoding="utf-8")
        assert re.search(r"function\s+escapeHtml|escapeHtml\s*[:=]", src), (
            "the helper does not escape agent-supplied names before they reach "
            "innerHTML"
        )

    def test_helper_falls_back_to_identifier(self):
        """FR-026: a stable identifier fallback when no name is recorded."""
        src = AGENT_DISPLAY_JS.read_text(encoding="utf-8")
        assert "agent_id" in src, (
            "the helper has no identifier fallback for an unnamed agent (FR-026)"
        )

    def test_helper_exposes_full_name_for_keyboard_and_touch(self):
        """
        FR-026c: the full name must be reachable without a mouse hover. A title
        attribute alone is hover-only; the element must also be focusable.
        """
        src = AGENT_DISPLAY_JS.read_text(encoding="utf-8")
        assert "title=" in src, "the full name is not exposed on the element"
        assert "tabindex" in src, (
            "the truncated name is not keyboard-reachable, so the full value is "
            "unavailable to anyone who cannot hover (FR-026c)"
        )


class TestTopPerformanceTable:
    """D21(a): names must not be silently cut to 8 characters."""

    def test_no_hard_substring_truncation(self, overview_js):
        assert "substring(0, 8)" not in overview_js, (
            "agent names are still hard-truncated to 8 characters with no way "
            "to see the rest (D21, FR-026a)"
        )
        assert not re.search(r"hostname\s*\.\s*substring\s*\(", overview_js), (
            "hostname is still truncated in JavaScript rather than by the "
            "shared display rule (FR-026a)"
        )

    def test_uses_the_shared_helper(self, overview_js):
        assert "AgentFmt" in overview_js, (
            "the top performance lists do not use the shared agent display "
            "helper (FR-026a–d)"
        )


class TestUpdateHistory:
    """D21(b): a truncated UUID is not an identification."""

    def test_no_bare_truncated_uuid(self, updates_html):
        assert "agent_id.slice(0, 8)" not in updates_html, (
            "update history still shows only the first 8 characters of the "
            "agent UUID (D21, FR-026)"
        )

    def test_shows_a_human_readable_name(self, updates_html):
        """
        FR-026: identify by human-readable name, with the identifier as a
        fallback — not the identifier instead of a name.
        """
        assert "AgentFmt" in updates_html, (
            "update history does not use the shared agent display helper, so it "
            "still identifies agents by identifier alone (D21, FR-026)"
        )


class TestNoRemainingHardTruncation:
    """
    FR-026b: truncation must never make two agents indistinguishable. A fixed
    character cut in JavaScript always can, so none should remain on the
    surfaces QA reported.
    """

    @pytest.mark.parametrize("path", [OVERVIEW_JS, UPDATES_HTML])
    def test_no_fixed_width_name_cut(self, path):
        src = path.read_text(encoding="utf-8")
        offenders = re.findall(
            r"(?:hostname|agent_name|agent_id)\s*\.\s*(?:substring|slice)\s*\(\s*0\s*,\s*\d+\s*\)",
            src,
        )
        assert not offenders, (
            f"{path.name} still cuts agent identity to a fixed width: {offenders} "
            f"(FR-026b)"
        )
