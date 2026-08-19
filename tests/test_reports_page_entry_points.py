"""
T061 + T062 / D18 / FR-025, FR-025a — reports page entry points.

QA's suggestion, recorded verbatim in defect-tracker.csv:

    "already we have separate features for getting the reports. So no need to
     add another generation button on the page and I will create some confusion."

The reports page carried two ways to do the same two things:

  * a top-level "Generate Report" button opening a unified modal, whose
    "Generate Now" mode duplicated the Activity Report section's own generate
    button, and whose "Schedule" mode duplicated the Email Schedules section's
    own "New Schedule" form;
  * the per-feature sections themselves.

FR-025 removes the duplicate top-level control. FR-025a is the guard that makes
that removal safe: every report reachable before the change must still be
reachable afterwards through its own feature. Both halves are asserted here —
removing the button is only correct while the per-feature entry points survive.
"""
from pathlib import Path

import pytest

REPORTS_TEMPLATE = (
    Path(__file__).parent.parent / "server" / "templates" / "dashboard" / "reports.html"
)


@pytest.fixture(scope="module")
def reports_html() -> str:
    return REPORTS_TEMPLATE.read_text(encoding="utf-8")


class TestRedundantControlRemoved:
    """FR-025: the duplicate top-level generation control is gone."""

    def test_no_control_opens_the_unified_modal(self, reports_html):
        """
        Asserts no *control* invokes the modal. The `openUnifiedModal` function
        definition itself may still exist — the modal and its handlers are dead
        code pending a follow-up deletion — but nothing on the page may reach it.
        """
        assert "onclick=\"openUnifiedModal()\"" not in reports_html, (
            "the redundant top-level 'Generate Report' control is still present; "
            "report generation is already reachable per-feature (D18, FR-025)"
        )
        assert "onclick='openUnifiedModal()'" not in reports_html

    def test_no_orphaned_trigger_element(self, reports_html):
        assert 'id="unified-modal-trigger"' not in reports_html, (
            "the unified modal trigger element is still in the page (D18, FR-025)"
        )


class TestExistingReportsStillReachable:
    """
    FR-025a: removing the duplicate must not make any report unreachable.

    These assertions are the reason the removal above is safe. If any of them
    starts failing, the removal has gone too far and a capability was lost.
    """

    def test_activity_report_generation_still_reachable(self, reports_html):
        assert "generateActivityReport()" in reports_html, (
            "the Activity Report section's own generate button is gone — "
            "report generation is now unreachable (FR-025a)"
        )
        assert 'id="ar-generate-btn"' in reports_html

    def test_email_schedule_creation_still_reachable(self, reports_html):
        assert "toggleNewScheduleForm()" in reports_html, (
            "the Email Schedules section's 'New Schedule' entry is gone — "
            "scheduling is now unreachable (FR-025a)"
        )
        assert "createSchedule()" in reports_html

    def test_schedules_section_still_reachable(self, reports_html):
        assert "showSection('schedules')" in reports_html, (
            "the Email Schedules section can no longer be opened (FR-025a)"
        )

    @pytest.mark.parametrize(
        "capability",
        [
            "runScheduleNow(",   # run an existing schedule on demand
            "deleteSchedule(",   # manage existing schedules
            "generateAgentCSV(",  # per-agent CSV export
        ],
    )
    def test_per_feature_capabilities_retained(self, reports_html, capability):
        assert capability in reports_html, (
            f"{capability} was removed alongside the duplicate control (FR-025a)"
        )


# ── T105 / D17 / FR-028 — icons render inside their badges ───────────────────

import re


class TestIconsRender:
    """
    D17: "Icons are missing inside the circle." (Login as admin -> Reports.)

    Root cause: the page used Font Awesome markup (`<i class="fas fa-...">`) in
    18 places, three of them inside `rounded-full` badges — but Font Awesome is
    never loaded. There is no stylesheet link in base.html or reports.html and
    nothing vendored under static/vendor; only Space Grotesk (a text font) is
    present. Every one of those elements therefore renders as nothing, leaving
    an empty circle.

    A second cause would have defeated the obvious fix: base.html applies
    `* { font-family: "Space Grotesk", sans-serif !important; }`, which overrides
    the icon font on every element. Loading Font Awesome alone would still have
    produced blank icons. The content-security policy also restricts font-src to
    'self', so a CDN stylesheet could not have worked either.

    Inline SVG avoids all three problems and matches the pattern the page
    already uses for its download buttons.
    """

    def test_no_unrenderable_icon_font_markup(self, reports_html):
        leftovers = re.findall(r'class="fa[srb] fa-[a-z-]+', reports_html)
        assert not leftovers, (
            f"{len(leftovers)} Font Awesome icons remain but the font is never "
            f"loaded, so they render as nothing: {sorted(set(leftovers))} (D17, FR-028)"
        )

    def test_icons_are_inline_svg(self, reports_html):
        assert "<svg" in reports_html, "the page has no inline SVG icons at all"

    def test_font_awesome_is_still_not_loaded(self, reports_html):
        """
        Guard against the other possible 'fix'. Loading Font Awesome would not
        work here — the global font-family !important rule overrides it and
        font-src is restricted to 'self'. If someone adds it later believing it
        solves D17, this test says why it will not.
        """
        assert "font-awesome" not in reports_html.lower(), (
            "Font Awesome was added, but the global `* { font-family: ... "
            "!important }` rule in base.html overrides it and CSP font-src is "
            "'self' — the icons will still not render"
        )
