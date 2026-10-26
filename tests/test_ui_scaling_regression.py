"""
Regression tests for UI scaling and responsiveness at 100%, 125%, and 150% zoom.
Verifies Phase 2 (Auto-Update Policy & Deploy Controls), Phase 3 (Shared Header),
and Phase 4 (Tables & Dashboard Grids).
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC_CSS = ROOT / "server" / "static" / "css"
TEMPLATES_DASHBOARD = ROOT / "server" / "templates" / "dashboard"


def test_updates_template_card_container_queries_and_stacking():
    """Verify updates.html defines responsive container queries and stacking for policy and deploy controls."""
    html_path = TEMPLATES_DASHBOARD / "updates.html"
    content = html_path.read_text(encoding="utf-8")

    # Container query declaration on update cards
    assert "container-type: inline-size" in content
    assert "container-name: updatecard" in content

    # Channel setting stacking rules
    assert ".policy-channel-row" in content
    assert "@container (max-width: 210px)" in content
    assert "@container (max-width: 235px)" in content
    assert "@container (max-width: 250px)" in content
    assert "flex-direction: column" in content

    # Enabled and Window toggle alignment
    assert ".policy-toggle-row" in content
    assert "justify-content: space-between" in content

    # Deploy action row stacking rules
    assert ".deploy-action-row" in content
    assert ".deploy-all-btn" in content

    # Canary range constraint
    assert ".canary-range" in content
    assert "box-sizing: border-box" in content
    assert "max-width: 100%" in content

    # Metrics grid responsive breakpoint (4 columns at xl, 2 at sm —
    # implemented as a custom CSS grid, previously Tailwind xl:grid-cols-4)
    assert ".update-metrics-grid" in content
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in content
    assert "grid-template-columns: minmax(135px, 0.75fr) minmax(135px, 0.75fr) minmax(240px, 1.25fr) minmax(320px, 1.65fr)" in content

    # Updates and History table min-widths
    assert "#updates-table" in content
    assert "min-width: 820px" in content
    assert "#history-table" in content
    assert "min-width: 760px" in content


def test_fleet_agents_table_horizontal_scroll_and_min_width():
    """Verify agents table and fleet container allow horizontal scrolling without clipping."""
    css_path = STATIC_CSS / "dashboard.css"
    content = css_path.read_text(encoding="utf-8")

    # Fleet table container must allow horizontal scrolling (not overflow-x: hidden)
    fleet_match = re.search(r"\.se-table-container-fleet\s*\{([^}]+)\}", content)
    assert fleet_match is not None
    fleet_block = fleet_match.group(1)
    assert "overflow-x: auto;" in fleet_block
    assert "overflow-x: hidden" not in fleet_block

    # Agents table must have a minimum width constraint to prevent header clipping
    match = re.search(r"#agents-table\s*\{([^}]+)\}", content)
    assert match is not None
    block = match.group(1)
    assert "min-width: 920px" in block


def test_shared_header_progressive_scaling_and_wrap():
    """Verify shared header implements progressive scaling, 768px wrap, and visible popover overflow."""
    css_path = STATIC_CSS / "header-responsive.css"
    content = css_path.read_text(encoding="utf-8")

    # Progressive gap and width reduction
    assert "@media (max-width: 1050px)" in content
    assert "@media (max-width: 900px)" in content
    assert "clamp(" in content

    # Breakpoint wrapping at 768px
    assert "@media (max-width: 768px)" in content

    # Header actions must NOT have overflow-x: auto which clips dropdowns/popovers
    assert ".se-header-actions" in content
    assert "overflow: visible;" in content

    # Menu and popover boundaries
    assert "max-width: calc(100vw - 1.5rem);" in content
