#!/usr/bin/env python3
"""
Weekly Report Email Dispatcher for SentinelEdge
Scans the reports/ folder for this week's generated HTML + PDF and sends them.
Runs independently from generation — if generation failed, this will detect it
and log clearly without crashing.

Cron (generate) : 0  8 * * 1  cd /path/to/weekly_cron && python3 send_weekly_report.py
Cron (email)    : 30 10 * * 1  cd /path/to/weekly_cron && python3 send_report_email.py

Logs: logs/send_report_email.log
"""

import os
import sys
import smtplib
import logging
from logging.handlers import RotatingFileHandler
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from datetime import date, timedelta, datetime, timezone
from pathlib import Path

# load .env from the server/ parent directory
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).resolve().parent.parent / '.env'
    load_dotenv(_env_path)
except ImportError:
    pass  # python-dotenv not installed, rely on shell environment

# ── config ───────────────────────────────────────────────────────────────────
SMTP_HOST     = os.environ.get('SMTP_HOST',     'smtp.office365.com')
SMTP_PORT     = int(os.environ.get('SMTP_PORT', '587'))
SMTP_USER     = os.environ.get('SMTP_USER',     '')
SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', '')   # set in environment, never hardcode
FROM_NAME     = os.environ.get('SMTP_FROM_NAME', 'SentinelEdge Reports')

# Comma-separated email lists from environment — e.g.:
#   REPORT_RECIPIENTS=alice@example.com,bob@example.com
#   REPORT_CC_RECIPIENTS=manager@example.com
_rcpt_raw  = os.environ.get('REPORT_RECIPIENTS',    '')
_cc_raw    = os.environ.get('REPORT_CC_RECIPIENTS', '')
RECIPIENTS    = [e.strip() for e in _rcpt_raw.split(',')  if e.strip()]
CC_RECIPIENTS = [e.strip() for e in _cc_raw.split(',')    if e.strip()]

REPORTS_DIR   = Path(__file__).parent / 'reports'
LOG_DIR       = Path(__file__).parent / 'logs'
LOG_FILE      = LOG_DIR / 'send_report_email.log'
# ─────────────────────────────────────────────────────────────────────────────

LOG_DIR.mkdir(exist_ok=True)

_fmt = logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s',
                         datefmt='%Y-%m-%d %H:%M:%S')
_fh = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024,
                          backupCount=4, encoding='utf-8')
_fh.setFormatter(_fmt)
_ch = logging.StreamHandler()
_ch.setFormatter(_fmt)
logging.basicConfig(level=logging.INFO, handlers=[_fh, _ch])
logger = logging.getLogger(__name__)


def get_last_week_dates():
    today  = date.today()
    offset = today.weekday() + 7          # always lands on previous Monday
    last_monday = today - timedelta(days=offset)
    last_sunday = last_monday + timedelta(days=6)
    return last_monday, last_sunday


def find_report_files(start_date, end_date, report_type='weekly', scope='team', identity=None):
    """
    Look for the HTML and PDF for the given period inside reports/.
    Searches both structured generated filenames and legacy team_weekly_ filenames.
    Returns (html_path, pdf_path) — either can be None if not found.
    """
    start_str = start_date.strftime('%Y-%m-%d')
    end_str = end_date.strftime('%Y-%m-%d')
    period = f"{start_str}_to_{end_str}" if start_str != end_str and report_type != 'daily' else start_str
    report_dir = REPORTS_DIR / f'{start_str}_to_{end_str}'

    search_dirs = [report_dir, REPORTS_DIR]
    target_ident = "team" if scope == "team" else (identity or "*")

    html_file = None
    pdf_file = None

    for d in search_dirs:
        if not d.exists():
            continue
        # 1. Search for new structured filename: <ident>_<type>_<period>_generated-*
        new_htmls = sorted(d.glob(f"{target_ident}_{report_type}_{period}_generated-*.html"), key=lambda p: p.stat().st_mtime, reverse=True)
        new_pdfs = sorted(d.glob(f"{target_ident}_{report_type}_{period}_generated-*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
        if new_htmls and not html_file:
            html_file = new_htmls[0]
        if new_pdfs and not pdf_file:
            pdf_file = new_pdfs[0]

        # 2. Also search with wildcard identity if not found yet
        if not html_file:
            gen_htmls = sorted(d.glob(f"*_{report_type}_{period}_generated-*.html"), key=lambda p: p.stat().st_mtime, reverse=True)
            if gen_htmls:
                html_file = gen_htmls[0]
        if not pdf_file:
            gen_pdfs = sorted(d.glob(f"*_{report_type}_{period}_generated-*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
            if gen_pdfs:
                pdf_file = gen_pdfs[0]

        # 3. Legacy discovery fallback
        if not html_file:
            legacy_html = d / f'team_weekly_{start_str}_to_{end_str}.html'
            if legacy_html.exists():
                html_file = legacy_html
        if not pdf_file:
            legacy_pdf = d / f'team_weekly_{start_str}_to_{end_str}.pdf'
            if legacy_pdf.exists():
                pdf_file = legacy_pdf

    return html_file, pdf_file


def is_report_fresh(html_file, start_date):
    """
    Check the report was generated after the week ended (i.e. not a stale
    leftover from a previous run). The week ends on Sunday — so the file
    must have been written on or after that Sunday.
    """
    if html_file is None:
        return False
    week_end = start_date + timedelta(days=6)   # Sunday
    file_mtime = date.fromtimestamp(html_file.stat().st_mtime)
    return file_mtime >= week_end


def send_email(html_file, pdf_file, start_date, end_date):
    """Attach available files and send via SMTP."""
    start_str = start_date.strftime('%Y-%m-%d')
    end_str   = end_date.strftime('%Y-%m-%d')

    msg = MIMEMultipart()
    msg['From']    = f'{FROM_NAME} <{SMTP_USER}>'
    msg['To']      = ', '.join(RECIPIENTS)
    msg['Cc']      = ', '.join(CC_RECIPIENTS)
    msg['Subject'] = f'Weekly Team Activity Report - {start_str} to {end_str}'

    has_html = bool(html_file and html_file.exists() and html_file.stat().st_size > 0)
    has_pdf = bool(pdf_file and pdf_file.exists() and pdf_file.stat().st_size > 0)

    if has_html and has_pdf:
        att_notice = "Both HTML and PDF versions are included for ease of review."
    elif has_pdf:
        att_notice = "A PDF version is included for ease of review."
    elif has_html:
        att_notice = "An HTML version is included for ease of review."
    else:
        logger.error("No valid files to attach — aborting send")
        return False

    support_contact = os.environ.get('SUPPORT_CONTACT', 'the CCD team')

    body = f"""Good Morning Team,

Please find attached the Weekly Team Activity Report for the period {start_str} to {end_str}.
This report presents an overview of team productivity, including:

  - Total team working hours and average hours per member
  - Top-performing team members
  - Most frequently used applications
  - Most visited websites
  - Detailed member-wise activity summary

{att_notice}
Should you require any additional information or clarification, please feel free to contact {support_contact}.

Best regards,
SentinelEdge Monitoring System

This is an automated report generated by SentinelEdge. Please do not reply to this email."""

    # Construct multipart/alternative for body
    body_part = MIMEMultipart('alternative')
    body_part.attach(MIMEText(body, 'plain'))

    try:
        server_dir = Path(__file__).resolve().parent.parent / 'server'
        if str(server_dir) not in sys.path:
            sys.path.insert(0, str(server_dir))
        from engines.report_engine import render_email_body_html
        att_meta = []
        if has_html:
            att_meta.append({'path': str(html_file), 'filename': html_file.name, 'content_type': 'text/html'})
        if has_pdf:
            att_meta.append({'path': str(pdf_file), 'filename': pdf_file.name, 'content_type': 'application/pdf'})
        html_summary = render_email_body_html(
            report_title="Weekly Team Activity Report",
            report_type="weekly",
            scope="team",
            team_name="Team",
            start_date=start_str,
            end_date=end_str,
            attachments=att_meta,
            support_contact=support_contact,
        )
        body_part.attach(MIMEText(html_summary, 'html', 'utf-8'))
    except Exception as e:
        logger.warning(f"Could not render HTML email body: {e}")

    msg.attach(body_part)

    attached = []
    files_to_attach = []
    if has_html:
        files_to_attach.append(html_file)
    if has_pdf:
        files_to_attach.append(pdf_file)

    for f in files_to_attach:
        with open(f, 'rb') as fh:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(fh.read())
        encoders.encode_base64(part)
        part.add_header('Content-Disposition',
                        f'attachment; filename={f.name}')
        msg.attach(part)
        attached.append(f.name)
        logger.info(f"Attached: {f.name}  ({f.stat().st_size // 1024} KB)")

    if not attached:
        logger.error("No files to attach — aborting send")
        return False

    if not RECIPIENTS:
        logger.error("REPORT_RECIPIENTS environment variable is not set — aborting send")
        return False

    if not SMTP_PASSWORD:
        logger.error("SMTP_PASSWORD environment variable is not set")
        return False

    try:
        logger.info(f"Connecting to {SMTP_HOST}:{SMTP_PORT} ...")
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
        try:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, RECIPIENTS + CC_RECIPIENTS, msg.as_string())
            logger.info(f"Email sent to {RECIPIENTS}, CC: {CC_RECIPIENTS}")
            return True
        finally:
            server.quit()
    except Exception as e:
        logger.error(f"SMTP send failed: {e}", exc_info=True)
        return False


def main():
    logger.info("=" * 60)
    logger.info("SentinelEdge Report Email Dispatcher — START")
    logger.info(f"Run time        : {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
    logger.info(f"Server date/day : {date.today()} ({date.today().strftime('%A')})")

    start_date, end_date = get_last_week_dates()
    logger.info(f"Expecting week  : {start_date} to {end_date}")
    logger.info("=" * 60)

    # ── step 1: locate report files ──────────────────────────────────────────
    html_file, pdf_file = find_report_files(start_date, end_date)

    if html_file is None:
        logger.error(
            f"HTML report not found for {start_date} to {end_date}. "
            f"Expected: {REPORTS_DIR}/{start_date}_to_{end_date}/"
            f"team_weekly_{start_date}_to_{end_date}.html"
        )
        logger.error("Generation cron may have failed — check logs/send_weekly_report.log")
        sys.exit(1)

    logger.info(f"HTML found : {html_file}")

    if pdf_file is None:
        logger.warning("PDF not found — will send HTML only")
    else:
        logger.info(f"PDF found  : {pdf_file}")

    # ── step 2: freshness check ───────────────────────────────────────────────
    if not is_report_fresh(html_file, start_date):
        file_date = date.fromtimestamp(html_file.stat().st_mtime)
        logger.error(
            f"Report file is STALE — file was last written on {file_date}, "
            f"but the reporting week ended on {start_date + timedelta(days=6)}. "
            f"This looks like a leftover from a previous run. "
            f"Generation cron likely failed this week."
        )
        sys.exit(1)

    # ── step 3: send ─────────────────────────────────────────────────────────
    success = send_email(html_file, pdf_file, start_date, end_date)

    if success:
        logger.info("Dispatch completed successfully ✅")
    else:
        logger.error("Dispatch failed — check SMTP credentials/connectivity ❌")
        sys.exit(1)


if __name__ == '__main__':
    main()
