"""
Static audit enforcing one date format product-wide (feature 037, SC-004).

SC-004 requires an audit of every date-bearing screen showing **zero**
deviations. A one-time manual pass cannot deliver that, because the next screen
someone builds reintroduces the problem — which is precisely how six separate
defects were reported across five screens in the first place.

So the audit is executable and runs in CI. It scans the source for the idioms
that caused the defects and fails if any returns.

The four idiom classes, each of which was missed by an earlier search pass:

  1. toLocaleDateString() / toLocaleString() / toLocaleTimeString()
     Follows the BROWSER's locale, so the same screen renders differently for
     different users — why several reports were never reproducible.

  2. Hardcoded Asia/Kolkata or a manual 5.5-hour offset
     Wrong for every viewer outside IST and blind to daylight saving. Applying
     both at once caused D11 (the generated time ran 5.5 hours ahead).

  3. Raw ISO string slicing — .replace('T',' ').slice(0,16)
     Prints stored UTC as though it were local, in YYYY-MM-DD order. This was
     D14 on the email schedules screen.

  4. Jinja strftime in templates
     Seven competing formats existed across the report templates alone.

Adding a genuinely necessary exception is fine — add it to ALLOWED with a reason.
"""
import os
import re
import sys
import unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parent.parent / "server"

# Files allowed to contain otherwise-forbidden idioms, with the reason.
ALLOWED = {
    # The shared formatters themselves: they implement the correct behaviour and
    # document the traps they replace.
    "static/js/datetime_format.js": "the canonical client formatter",
    "static/js/timezone_utils.js": "delegates to DateFmt; header documents its history",
    "utils/datetime_format.py": "the canonical server formatter",
}

FORBIDDEN = [
    (
        "browser-locale formatting",
        re.compile(r"\.toLocale(Date|Time)?String\s*\("),
        "use DateFmt.formatDate / DateFmt.formatDateTime",
    ),
    (
        "hardcoded IST timezone",
        re.compile(r"Asia/Kolkata"),
        "render in the viewer's timezone via the shared formatter",
    ),
    (
        "manual 5.5-hour offset",
        re.compile(r"5\.5\s*\*\s*(60\s*\*\s*60|3600)"),
        "never hand-roll a timezone offset; use the shared formatter",
    ),
    (
        "raw ISO string slicing",
        re.compile(r"\.replace\(\s*['\"]T['\"]\s*,\s*['\"] ['\"]\s*\)"),
        "use DateFmt.formatDateTime — slicing skips timezone conversion entirely",
    ),
]


def _strip_comments(text, suffix):
    """Drop comments so documentation *about* a forbidden idiom is not flagged."""
    if suffix in (".js",):
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        text = re.sub(r"^\s*//.*$", "", text, flags=re.M)
        text = re.sub(r"^\s*\*.*$", "", text, flags=re.M)
    elif suffix in (".py",):
        text = re.sub(r"^\s*#.*$", "", text, flags=re.M)
        text = re.sub(r'"""(?:.|\n)*?"""', "", text)
    elif suffix in (".html",):
        text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
        text = re.sub(r"^\s*//.*$", "", text, flags=re.M)
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return text


def _scan(paths):
    findings = []
    for path in paths:
        rel = path.relative_to(SERVER).as_posix()
        if rel in ALLOWED:
            continue
        body = _strip_comments(path.read_text(encoding="utf-8", errors="replace"), path.suffix)
        for label, pattern, remedy in FORBIDDEN:
            for match in pattern.finditer(body):
                line = body[: match.start()].count("\n") + 1
                findings.append(f"{rel}:{line}  {label} -> {remedy}")
    return findings


class TestNoForbiddenDateIdioms(unittest.TestCase):
    """SC-004: zero deviating screens, enforced rather than asserted."""

    def test_dashboard_templates_use_the_shared_formatter(self):
        findings = _scan(sorted((SERVER / "templates").rglob("*.html")))
        self.assertEqual([], findings, "\n" + "\n".join(findings))

    def test_static_javascript_uses_the_shared_formatter(self):
        """
        The directory a four-pass search kept missing. It held an entire
        competing IST formatting library plus 16 further sites.
        """
        findings = _scan(sorted((SERVER / "static" / "js").rglob("*.js")))
        self.assertEqual([], findings, "\n" + "\n".join(findings))

    def test_no_strftime_left_in_jinja_templates(self):
        """
        Jinja templates must use the fmt_date / fmt_datetime filters.

        '%a' is permitted: a weekday abbreviation on a chart axis is a label,
        not a date, and FR-007 governs dates.
        """
        offenders = []
        for path in sorted((SERVER / "templates").rglob("*.html")):
            body = _strip_comments(path.read_text(encoding="utf-8", errors="replace"), ".html")
            for match in re.finditer(r"strftime\(\s*['\"]([^'\"]*)['\"]\s*\)", body):
                if match.group(1) == "%a":
                    continue
                line = body[: match.start()].count("\n") + 1
                offenders.append(
                    f"{path.relative_to(SERVER).as_posix()}:{line}  "
                    f"strftime('{match.group(1)}') -> use | fmt_date or | fmt_datetime"
                )
        self.assertEqual([], offenders, "\n" + "\n".join(offenders))


class TestFormatterIsReachable(unittest.TestCase):
    """A formatter nothing loads cannot fix anything."""

    def test_client_formatter_is_loaded_by_the_base_template(self):
        base = (SERVER / "templates" / "dashboard" / "base.html").read_text(
            encoding="utf-8", errors="replace"
        )
        self.assertIn("js/datetime_format.js", base)

    def test_client_formatter_loads_before_other_page_scripts(self):
        base = (SERVER / "templates" / "dashboard" / "base.html").read_text(
            encoding="utf-8", errors="replace"
        )
        self.assertLess(
            base.index("js/datetime_format.js"),
            base.index("js/utils.js"),
            "datetime_format.js must load before scripts that render dates",
        )

    def test_jinja_filters_are_registered_in_both_environments(self):
        """
        Two Jinja environments exist: Flask's, and report_engine's standalone one
        for email/PDF. A filter registered in only one breaks the other at render
        time — the same split that caused D12.
        """
        for rel in ("server_app.py", "engines/report_engine.py"):
            body = (SERVER / rel).read_text(encoding="utf-8", errors="replace")
            self.assertIn("fmt_date", body, f"{rel} does not register fmt_date")
            self.assertIn("fmt_datetime", body, f"{rel} does not register fmt_datetime")


if __name__ == "__main__":
    unittest.main()
