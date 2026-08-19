"""
T060 / D09 / FR-024 — printed reports must stay aligned and unclipped.

QA repro: Login as admin -> Reports -> select individual agent -> View Report
-> click Print PDF. Actual result: "report alignment is not proper."

The Print PDF button lives in dashboard/agent_report.html, which extends
dashboard/base.html and inherits its print styles. Those styles hid the nav and
flattened dark backgrounds, but never addressed the two things that actually
break a printed dashboard:

  1. Dashboard tables sit inside Tailwind `overflow-x-auto` wrappers. On screen
     that scrolls; on paper an overflow container *clips* everything past the
     visible width, so right-hand columns silently vanish.
  2. A table spanning a page break loses its header row, so the continuation
     reads as misaligned columns of unlabelled numbers.

These are CSS rules, so they are asserted against the stylesheet text rather
than a rendered page — a rendering assertion would need a real print engine.
The point is to pin the contract so the rules cannot be dropped again.
"""
import re
from pathlib import Path

import pytest

BASE_TEMPLATE = (
    Path(__file__).parent.parent / "server" / "templates" / "dashboard" / "base.html"
)


def _print_css() -> str:
    """Concatenate every @media print block in base.html."""
    html = BASE_TEMPLATE.read_text(encoding="utf-8")
    blocks = []
    for match in re.finditer(r"@media\s+print\s*\{", html):
        start = match.end()
        depth = 1
        i = start
        while i < len(html) and depth:
            if html[i] == "{":
                depth += 1
            elif html[i] == "}":
                depth -= 1
            i += 1
        blocks.append(html[start : i - 1])
    return "\n".join(blocks)


class TestPrintLayout:
    def test_base_template_has_print_styles(self):
        assert _print_css().strip(), "base.html defines no @media print rules at all"

    def test_overflow_containers_are_unclipped(self):
        """
        Tailwind's overflow-x-auto wrapper clips in print. Without this, the
        right-hand columns of every wide table are cut off the page — the
        single most likely cause of D09.
        """
        css = _print_css()
        assert "overflow-x-auto" in css, (
            "print styles do not unclip .overflow-x-auto wrappers, so wide "
            "tables will be cut off at the page edge (D09, FR-024)"
        )
        assert re.search(r"overflow\s*:\s*visible", css), (
            "overflow containers are not set to visible in print (D09, FR-024)"
        )

    def test_tables_fit_the_page_width(self):
        css = _print_css()
        assert re.search(r"table\s*\{[^}]*width\s*:\s*100%", css, re.S), (
            "tables are not constrained to the page width in print (D09, FR-024)"
        )

    def test_table_headers_repeat_across_pages(self):
        """
        FR-024: content must stay aligned across page breaks. A split table
        without a repeated header is unreadable on the second page.
        """
        css = _print_css()
        assert re.search(r"thead\s*\{[^}]*table-header-group", css, re.S), (
            "thead does not repeat across printed pages (D09, FR-024)"
        )

    def test_rows_do_not_split_across_pages(self):
        css = _print_css()
        assert re.search(r"tr\s*\{[^}]*(page-)?break-inside\s*:\s*avoid", css, re.S), (
            "table rows may split across a page break (D09, FR-024)"
        )

    @pytest.mark.parametrize("selector", ["nav", ".no-print"])
    def test_chrome_is_hidden_in_print(self, selector):
        """Existing behaviour — must not regress while fixing alignment."""
        assert selector in _print_css(), f"{selector} is no longer hidden in print"
