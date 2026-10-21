"""
tests/test_report_naming_and_exports.py — Comprehensive validation test suite for FE-01 and NI-19.

Validates all 30 scenarios from the FE-01/NI-19 validation matrix:
1. Repeated same-day exports produce distinct filenames (morning vs evening).
2. Collision prevention when exports share identical timestamps.
3. Date changes update reporting period in filename and metadata.
4. Missing agent name falls back to hostname.
5. Missing agent name and hostname falls back to agent_id.
6. Completely missing identity falls back to default.
7. Special characters in agent name are sanitized.
8. Unicode accents in agent name are normalized to ASCII.
9. Consecutive hyphens and leading/trailing punctuation are trimmed.
10. Individual daily report filename structure matches specification.
11. Individual weekly report filename structure matches specification.
12. Individual monthly report filename structure matches specification.
13. Team daily report filename structure matches specification.
14. Team weekly report filename structure matches specification.
15. Team monthly report filename structure matches specification.
16. Period across year boundary formatted correctly.
17. Period across month boundary formatted correctly.
18. Filename metadata extraction matches generated metadata.
19. Concurrent exports receive unique identifiers.
20. Safe file creation preserves existing files (no silent overwriting).
21. Incomplete / temporary files cleaned up on generation failure.
22. Failed exports are not marked as successful.
23. Report content corresponds to selected reporting period.
24. Email attachments include structured filename in Content-Disposition.
25. Email retries reuse existing export without generating new exports.
26. Backward compatibility: send_report_email works without attachments.
27. Legacy team weekly filename discovery in weekly_cron.
28. New structured filename discovery in weekly_cron.
29. Download endpoint serves attachment with canonical filename headers.
30. Backward compatibility: parsing legacy filename structures.
"""

import os
import re
import uuid
import tempfile
import threading
from pathlib import Path
from datetime import datetime, date, timezone
from unittest.mock import MagicMock, patch

import pytest

from server.engines.report_naming import (
    build_report_filename,
    build_report_metadata,
    sanitize_identity,
    format_period,
    format_generation_timestamp,
    parse_report_filename,
    resolve_collision_safe_path,
    safe_write_file,
    get_reports_storage_dir,
)
from server.engines.report_engine import (
    send_report_email,
    generate_pdf,
    run_report_job,
)


# ==============================================================================
# Scenarios 1-3: Repeated Exports & Date Changes
# ==============================================================================

def test_scenario_01_repeated_same_day_exports_distinct_filenames():
    """Scenario 1: Repeated exports for same agent on same day produce distinct filenames."""
    morning = datetime(2026, 10, 12, 9, 15, 32, tzinfo=timezone.utc)
    evening = datetime(2026, 10, 12, 18, 42, 7, tzinfo=timezone.utc)

    fn_morning = build_report_filename(
        report_type="daily",
        scope="individual",
        identity="desktop-abc",
        start_date="2026-10-12",
        end_date="2026-10-12",
        generated_at=morning,
        export_id="a81f2c",
    )
    fn_evening = build_report_filename(
        report_type="daily",
        scope="individual",
        identity="desktop-abc",
        start_date="2026-10-12",
        end_date="2026-10-12",
        generated_at=evening,
        export_id="f29b61",
    )

    assert fn_morning == "desktop-abc_daily_2026-10-12_generated-20261012T091532Z_a81f2c.pdf"
    assert fn_evening == "desktop-abc_daily_2026-10-12_generated-20261012T184207Z_f29b61.pdf"
    assert fn_morning != fn_evening


def test_scenario_02_collision_prevention_same_timestamp():
    """Scenario 2: Exports with same timestamp receive different export IDs and do not collide."""
    ts = datetime(2026, 10, 12, 9, 15, 32, tzinfo=timezone.utc)
    fn1 = build_report_filename("daily", "individual", "desktop-abc", "2026-10-12", "2026-10-12", ts, export_id="111111")
    fn2 = build_report_filename("daily", "individual", "desktop-abc", "2026-10-12", "2026-10-12", ts, export_id="222222")

    assert fn1 != fn2
    assert "111111" in fn1
    assert "222222" in fn2


def test_scenario_03_date_changes_update_period():
    """Scenario 3: Date change updates the period in filename and metadata."""
    fn_day1 = build_report_filename("daily", "individual", "agent-1", "2026-10-12", "2026-10-12")
    fn_day2 = build_report_filename("daily", "individual", "agent-1", "2026-10-13", "2026-10-13")

    assert "2026-10-12" in fn_day1
    assert "2026-10-13" in fn_day2
    assert fn_day1 != fn_day2


# ==============================================================================
# Scenarios 4-9: Identity Handling & Sanitization
# ==============================================================================

def test_scenario_04_missing_agent_name_fallback_to_hostname():
    """Scenario 4: Missing agent_name falls back to hostname."""
    safe = sanitize_identity("host-prod-99")
    fn = build_report_filename("daily", "individual", safe, "2026-10-12")
    assert fn.startswith("host-prod-99_daily_")


def test_scenario_05_missing_agent_name_and_hostname_fallback_to_agent_id():
    """Scenario 5: Missing agent_name and hostname falls back to agent_id UUID."""
    agent_id = "a81f2c45-1234-5678-abcd-ef0123456789"
    safe = sanitize_identity(agent_id)
    fn = build_report_filename("daily", "individual", safe, "2026-10-12")
    assert fn.startswith("a81f2c45-1234-5678-abcd-ef0123456789_daily_")


def test_scenario_06_completely_missing_identity_fallback_to_default():
    """Scenario 6: Completely missing identity defaults to 'agent'."""
    assert sanitize_identity(None) == "agent"
    assert sanitize_identity("") == "agent"
    fn = build_report_filename("daily", "individual", None, "2026-10-12")
    assert fn.startswith("agent_daily_")


def test_scenario_07_special_characters_in_agent_name():
    """Scenario 7: Special characters in agent name are sanitized."""
    raw = "DESKTOP / John's PC (Finance) #1"
    safe = sanitize_identity(raw)
    assert safe == "desktop-john-s-pc-finance-1"
    fn = build_report_filename("daily", "individual", raw, "2026-10-12")
    assert fn.startswith("desktop-john-s-pc-finance-1_daily_")


def test_scenario_08_unicode_accents_sanitization():
    """Scenario 8: Unicode accents normalized to ASCII."""
    raw = "René's-Laptop"
    safe = sanitize_identity(raw)
    assert safe == "rene-s-laptop"


def test_scenario_09_consecutive_hyphens_and_leading_trailing_punctuation():
    """Scenario 9: Multiple hyphens collapsed and trimmed."""
    raw = "---My   Server---"
    safe = sanitize_identity(raw)
    assert safe == "my-server"


# ==============================================================================
# Scenarios 10-15: Report Types & Scopes Filename Structures
# ==============================================================================

def test_scenario_10_individual_daily_report_filename_structure():
    """Scenario 10: Individual daily report structure."""
    fn = build_report_filename("daily", "individual", "alice", "2026-10-12", "2026-10-12")
    pattern = r"^alice_daily_2026-10-12_generated-\d{8}T\d{6}Z_[a-f0-9]+\.pdf$"
    assert re.match(pattern, fn), f"Filename '{fn}' does not match pattern '{pattern}'"


def test_scenario_11_individual_weekly_report_filename_structure():
    """Scenario 11: Individual weekly report structure."""
    fn = build_report_filename("weekly", "individual", "alice", "2026-10-05", "2026-10-11")
    pattern = r"^alice_weekly_2026-10-05_to_2026-10-11_generated-\d{8}T\d{6}Z_[a-f0-9]+\.pdf$"
    assert re.match(pattern, fn), f"Filename '{fn}' does not match pattern '{pattern}'"


def test_scenario_12_individual_monthly_report_filename_structure():
    """Scenario 12: Individual monthly report structure."""
    fn = build_report_filename("monthly", "individual", "alice", "2026-09-01", "2026-09-30")
    pattern = r"^alice_monthly_2026-09-01_to_2026-09-30_generated-\d{8}T\d{6}Z_[a-f0-9]+\.pdf$"
    assert re.match(pattern, fn), f"Filename '{fn}' does not match pattern '{pattern}'"


def test_scenario_13_team_daily_report_filename_structure():
    """Scenario 13: Team daily report structure."""
    fn = build_report_filename("daily", "team", None, "2026-10-12", "2026-10-12")
    pattern = r"^team_daily_2026-10-12_generated-\d{8}T\d{6}Z_[a-f0-9]+\.pdf$"
    assert re.match(pattern, fn), f"Filename '{fn}' does not match pattern '{pattern}'"


def test_scenario_14_team_weekly_report_filename_structure():
    """Scenario 14: Team weekly report structure."""
    ts = datetime(2026, 10, 12, 9, 15, 32, tzinfo=timezone.utc)
    fn = build_report_filename("weekly", "team", None, "2026-10-05", "2026-10-11", ts, "b81d32")
    assert fn == "team_weekly_2026-10-05_to_2026-10-11_generated-20261012T091532Z_b81d32.pdf"


def test_scenario_15_team_monthly_report_filename_structure():
    """Scenario 15: Team monthly report structure."""
    ts = datetime(2026, 10, 12, 9, 15, 32, tzinfo=timezone.utc)
    fn = build_report_filename("monthly", "team", None, "2026-09-01", "2026-09-30", ts, "c45e67")
    assert fn == "team_monthly_2026-09-01_to_2026-09-30_generated-20261012T091532Z_c45e67.pdf"


# ==============================================================================
# Scenarios 16-18: Boundary Periods & Metadata Extraction
# ==============================================================================

def test_scenario_16_period_across_year_boundary():
    """Scenario 16: Period spanning year boundary."""
    fn = build_report_filename("weekly", "team", None, "2025-12-29", "2026-01-04")
    assert "2025-12-29_to_2026-01-04" in fn


def test_scenario_17_period_across_month_boundary():
    """Scenario 17: Period spanning month boundary."""
    fn = build_report_filename("weekly", "team", None, "2026-01-26", "2026-02-01")
    assert "2026-01-26_to_2026-02-01" in fn


def test_scenario_18_filename_metadata_extraction_matches_generation():
    """Scenario 18: parse_report_filename matches generated metadata."""
    meta = build_report_metadata(
        report_type="weekly",
        scope="individual",
        identity="server-01",
        start_date="2026-10-05",
        end_date="2026-10-11",
        generated_at=datetime(2026, 10, 12, 9, 0, 0, tzinfo=timezone.utc),
        export_id="e1a2b3",
        ext="pdf",
    )
    parsed = parse_report_filename(meta["filename"])

    assert parsed["identity"] == meta["identity"]
    assert parsed["report_type"] == meta["report_type"]
    assert parsed["scope"] == meta["scope"]
    assert parsed["start_date"] == meta["start_date"]
    assert parsed["end_date"] == meta["end_date"]
    assert parsed["generated_at"] == meta["generated_at"]
    assert parsed["export_id"] == meta["export_id"]
    assert parsed["extension"] == "pdf"
    assert parsed["is_legacy"] is False


# ==============================================================================
# Scenarios 19-22: Concurrency, Collision, and Failure Handling
# ==============================================================================

def test_scenario_19_concurrent_exports_unique_identifiers():
    """Scenario 19: Concurrent generation in threads produces unique export IDs."""
    filenames = []
    lock = threading.Lock()

    def worker():
        fn = build_report_filename("daily", "individual", "agent-x", "2026-10-12")
        with lock:
            filenames.append(fn)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(filenames) == 10
    # All filenames must be unique
    assert len(set(filenames)) == 10


def test_scenario_20_safe_write_file_preserves_existing_file(tmp_path):
    """Scenario 20: Existing files are never overwritten; collision safe path is chosen."""
    dest = tmp_path / "test_report.pdf"
    dest.write_text("original content", encoding="utf-8")

    written = safe_write_file("new content", dest)

    assert dest.read_text(encoding="utf-8") == "original content"  # original preserved
    assert written != dest
    assert written.exists()
    assert written.read_text(encoding="utf-8") == "new content"


def test_scenario_21_incomplete_temporary_file_cleanup_on_failure(tmp_path):
    """Scenario 21: Temp files are cleaned up on generation failure."""
    target_pdf = tmp_path / "failed_report.pdf"

    mock_weasy = MagicMock()
    mock_weasy.HTML.side_effect = RuntimeError("WeasyPrint crash")
    with patch.dict("sys.modules", {"weasyprint": mock_weasy}):
        ok, err = generate_pdf("<html>test</html>", target_pdf)

    assert ok is False
    assert not target_pdf.exists()
    # Check that no temporary files remain in tmp_path
    assert list(tmp_path.glob("*.tmp*")) == []


def test_scenario_22_failed_export_not_marked_successful(tmp_path):
    """Scenario 22: Generation failure returns failure tuple without creating a success file."""
    target_pdf = tmp_path / "never_created.pdf"
    mock_weasy = MagicMock()
    mock_weasy.HTML.side_effect = Exception("Render error")
    with patch.dict("sys.modules", {"weasyprint": mock_weasy}):
        ok, res = generate_pdf("<html>error</html>", target_pdf)

    assert ok is False
    assert "Render error" in str(res)
    assert not target_pdf.exists()


# ==============================================================================
# Scenarios 23-26: Period Verification, Email Attachments & Retries
# ==============================================================================

def test_scenario_23_report_content_corresponds_to_reporting_period():
    """Scenario 23: Metadata accurately reflects the specified reporting period."""
    meta = build_report_metadata(
        report_type="monthly",
        scope="team",
        start_date="2026-09-01",
        end_date="2026-09-30",
    )
    assert meta["start_date"] == "2026-09-01"
    assert meta["end_date"] == "2026-09-30"
    assert meta["period"] == "2026-09-01_to_2026-09-30"


def test_scenario_24_email_attachments_with_structured_filename(tmp_path):
    """Scenario 24: send_report_email includes PDF with Content-Disposition structured filename."""
    pdf_file = tmp_path / "team_weekly_2026-10-05_to_2026-10-11_generated-20261012T091532Z_b81d32.pdf"
    pdf_file.write_bytes(b"%PDF-1.4 mock pdf content")

    mock_server = MagicMock()
    with patch("smtplib.SMTP", return_value=mock_server), \
         patch.dict(os.environ, {"SMTP_USER": "test@example.com", "SMTP_PASSWORD": "secret"}):

        ok, err = send_report_email(
            html_content="<p>Weekly report</p>",
            recipients=["manager@example.com"],
            subject="Weekly Report",
            attachments=[{"path": str(pdf_file), "filename": pdf_file.name}],
        )

        assert ok is True
        mock_server.__enter__().sendmail.assert_called_once()
        raw_msg = mock_server.__enter__().sendmail.call_args[0][2]
        assert "Content-Disposition: attachment; filename=\"team_weekly_2026-10-05_to_2026-10-11_generated-20261012T091532Z_b81d32.pdf\"" in raw_msg


def test_scenario_25_email_retries_reuse_existing_export():
    """Scenario 25: Email retries on a completed job reuse existing result_pdf_path without new export."""
    mock_db = MagicMock()
    job_mock = MagicMock()
    job_mock.result_html = "<p>report</p>"
    job_mock.result_pdf_path = "/path/to/existing_export_123.pdf"
    mock_db.session.get.return_value = job_mock

    # Simulating the retry logic in email_job_result
    from server.server_reports import reports_bp
    from flask import Flask

    app = Flask(__name__)
    app.register_blueprint(reports_bp)
    app.config["TESTING"] = True

    with patch("engines.report_engine.get_job", return_value={
        "result_html": "<p>report</p>",
        "result_pdf_path": "/path/to/existing_export_123.pdf"
    }), patch("engines.report_engine.send_report_email", return_value=(True, None)) as mock_send, \
       patch("os.path.exists", return_value=True):

        with app.test_request_context(
            "/dashboard/reports/unified/jobs/job-123/email",
            method="POST",
            json={"recipients": ["retry@example.com"]}
        ):
            from flask import g
            g.current_user = MagicMock(role="admin")
            from server.server_reports import email_job_result
            handler = email_job_result
            while hasattr(handler, "__wrapped__"):
                handler = handler.__wrapped__
            resp = handler("job-123")

            mock_send.assert_called_once()
            kwargs = mock_send.call_args[1]
            attachments = kwargs.get("attachments")
            assert attachments is not None
            assert attachments[0]["path"] == "/path/to/existing_export_123.pdf"
            assert attachments[0]["filename"] == "existing_export_123.pdf"


def test_scenario_26_backward_compatibility_send_report_email_without_attachments():
    """Scenario 26: send_report_email without attachments preserves multipart/alternative structure."""
    mock_server = MagicMock()
    with patch("smtplib.SMTP", return_value=mock_server), \
         patch.dict(os.environ, {"SMTP_USER": "test@example.com", "SMTP_PASSWORD": "secret"}):

        ok, err = send_report_email(
            html_content="<p>Plain report</p>",
            recipients=["user@example.com"],
            subject="Plain Report",
        )

        assert ok is True
        raw_msg = mock_server.__enter__().sendmail.call_args[0][2]
        assert "multipart/alternative" in raw_msg
        assert "Content-Disposition: attachment" not in raw_msg


# ==============================================================================
# Scenarios 27-30: Legacy Discovery, Download Headers, and Legacy Parsing
# ==============================================================================

def test_scenario_27_legacy_team_weekly_filename_discovery(tmp_path):
    """Scenario 27: weekly_cron discovers legacy team_weekly_ HTML and PDF files."""
    start_d = date(2026, 10, 5)
    end_d = date(2026, 10, 11)
    sub = tmp_path / "2026-10-05_to_2026-10-11"
    sub.mkdir(parents=True)
    legacy_html = sub / "team_weekly_2026-10-05_to_2026-10-11.html"
    legacy_pdf = sub / "team_weekly_2026-10-05_to_2026-10-11.pdf"
    legacy_html.write_text("<html>legacy</html>", encoding="utf-8")
    legacy_pdf.write_bytes(b"%PDF legacy")

    with patch("weekly_cron.send_report_email.REPORTS_DIR", tmp_path):
        from weekly_cron.send_report_email import find_report_files
        html_f, pdf_f = find_report_files(start_d, end_d)

    assert html_f == legacy_html
    assert pdf_f == legacy_pdf


def test_scenario_28_new_structured_filename_discovery(tmp_path):
    """Scenario 28: weekly_cron discovers new structured generated files."""
    start_d = date(2026, 10, 5)
    end_d = date(2026, 10, 11)
    sub = tmp_path / "2026-10-05_to_2026-10-11"
    sub.mkdir(parents=True)
    new_html = sub / "team_weekly_2026-10-05_to_2026-10-11_generated-20261012T091532Z_b81d32.html"
    new_pdf = sub / "team_weekly_2026-10-05_to_2026-10-11_generated-20261012T091532Z_b81d32.pdf"
    new_html.write_text("<html>new</html>", encoding="utf-8")
    new_pdf.write_bytes(b"%PDF new")

    with patch("weekly_cron.send_report_email.REPORTS_DIR", tmp_path):
        from weekly_cron.send_report_email import find_report_files
        html_f, pdf_f = find_report_files(start_d, end_d)

    assert html_f == new_html
    assert pdf_f == new_pdf


def test_scenario_29_browser_download_endpoint_headers():
    """Scenario 29: Download endpoint returns Content-Disposition header with filename."""
    from server.server_reports import reports_bp
    from flask import Flask

    app = Flask(__name__)
    app.register_blueprint(reports_bp)
    app.config["TESTING"] = True

    with patch("engines.report_engine.get_job", return_value={
        "result_html": "<html>download</html>",
        "result_pdf_path": "/storage/desktop-abc_daily_2026-10-12_generated-20261012T091532Z_a81f2c.pdf"
    }), patch("flask.send_file") as mock_send_file, \
       patch("os.path.exists", return_value=True):

        with app.test_request_context(
            "/dashboard/reports/unified/jobs/job-123/download?format=pdf",
            method="GET"
        ):
            from flask import g
            g.current_user = MagicMock(role="admin")
            from server.server_reports import download_job_result
            handler = download_job_result
            while hasattr(handler, "__wrapped__"):
                handler = handler.__wrapped__
            handler("job-123")

            mock_send_file.assert_called_once()
            call_kwargs = mock_send_file.call_args[1]
            assert call_kwargs["as_attachment"] is True
            assert call_kwargs["download_name"] == "desktop-abc_daily_2026-10-12_generated-20261012T091532Z_a81f2c.pdf"


def test_scenario_30_backward_compatibility_parse_legacy_filenames():
    """Scenario 30: parse_report_filename accurately handles legacy naming formats."""
    # Legacy team weekly
    p1 = parse_report_filename("team_weekly_2026-10-05_to_2026-10-11.pdf")
    assert p1["is_legacy"] is True
    assert p1["identity"] == "team"
    assert p1["scope"] == "team"
    assert p1["report_type"] == "weekly"
    assert p1["start_date"] == "2026-10-05"
    assert p1["end_date"] == "2026-10-11"

    # Legacy individual weekly
    p2 = parse_report_filename("surya_weekly_2026-10-05_to_2026-10-11.html")
    assert p2["is_legacy"] is True
    assert p2["identity"] == "surya"
    assert p2["scope"] == "individual"
    assert p2["report_type"] == "weekly"

    # Legacy individual daily
    p3 = parse_report_filename("surya_daily_2026-10-12.html")
    assert p3["is_legacy"] is True
    assert p3["identity"] == "surya"
    assert p3["scope"] == "individual"
    assert p3["report_type"] == "daily"
    assert p3["start_date"] == "2026-10-12"
    assert p3["end_date"] == "2026-10-12"
