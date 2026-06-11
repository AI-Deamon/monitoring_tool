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


def find_report_files(start_date, end_date):
    """
    Look for the HTML and PDF for the given week inside reports/.
    Returns (html_path, pdf_path) — either can be None if not found.
    """
    start_str  = start_date.strftime('%Y-%m-%d')
    end_str    = end_date.strftime('%Y-%m-%d')
    report_dir = REPORTS_DIR / f'{start_str}_to_{end_str}'

    html_file = report_dir / f'team_weekly_{start_str}_to_{end_str}.html'
    pdf_file  = report_dir / f'team_weekly_{start_str}_to_{end_str}.pdf'

    html = html_file if html_file.exists() else None
    pdf  = pdf_file  if pdf_file.exists()  else None

    return html, pdf


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

    body = f"""Good Morning Team,

Please find attached the Weekly Team Activity Report for the period {start_str} to {end_str}.
This report presents an overview of team productivity, including:

  - Total team working hours and average hours per member
  - Top-performing team members
  - Most frequently used applications
  - Most visited websites
  - Detailed member-wise activity summary

Both HTML and PDF versions are included for ease of review.
Should you require any additional information or clarification, please feel free to contact the CCD team.

Best regards,
SentinelEdge Monitoring System

This is an automated report generated by SentinelEdge. Please do not reply to this email."""

    msg.attach(MIMEText(body, 'plain'))

    attached = []
    for f in [html_file, pdf_file]:
        if f and f.exists():
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
