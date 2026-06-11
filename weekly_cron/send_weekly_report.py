#!/usr/bin/env python3
"""
Weekly Report Generator Cron for SentinelEdge
Generates the team HTML + PDF report and exits.
Email is sent separately by send_report_email.py so the two concerns are
fully decoupled — if generation fails, email dispatcher detects it and logs
clearly without crashing.

Cron (generate) : 0  8 * * 1  cd /path/to/weekly_cron && DATABASE_URL=... python3 send_weekly_report.py
Cron (email)    : 30 10 * * 1  cd /path/to/weekly_cron && python3 send_report_email.py

Logs: logs/send_weekly_report.log
"""

import os
import sys
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, timedelta, date, timezone
from pathlib import Path

# load .env from the server/ parent directory
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).resolve().parent.parent / '.env'
    load_dotenv(_env_path)
except ImportError:
    pass  # python-dotenv not installed, rely on shell environment

REPORT_SCRIPT = Path(__file__).parent / 'generate_weekly_reports.py'
LOG_DIR       = Path(__file__).parent / 'logs'
LOG_FILE      = LOG_DIR / 'send_weekly_report.log'

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


def cleanup_old_reports(keep_weeks=8):
    """Delete report folders older than keep_weeks weeks."""
    reports_dir = Path(__file__).parent / 'reports'
    if not reports_dir.exists():
        return
    cutoff = date.today() - timedelta(weeks=keep_weeks)
    for folder in sorted(reports_dir.iterdir()):
        if not folder.is_dir():
            continue
        try:
            # folder name starts with the start date e.g. 2026-04-27_to_...
            folder_date = date.fromisoformat(folder.name[:10])
            if folder_date < cutoff:
                import shutil
                shutil.rmtree(folder)
                logger.info(f"Deleted old report folder: {folder.name}")
        except (ValueError, IndexError):
            pass  # skip folders that don't match the date pattern


def generate_report(start_date, end_date):
    """Invoke generate_weekly_reports.py as a subprocess and stream its output to the log."""
    import subprocess

    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        logger.error("DATABASE_URL environment variable is not set")
        return False

    cmd = [
        sys.executable,
        str(REPORT_SCRIPT),
        '--team',
        '--start', start_date.strftime('%Y-%m-%d'),
        '--end',   end_date.strftime('%Y-%m-%d'),
        '--db-url', db_url,
    ]

    logger.info(f"Running generator for {start_date} to {end_date}")
    result = subprocess.run(cmd, capture_output=True, text=True)

    for line in result.stdout.strip().splitlines():
        logger.info(f"  [generator] {line}")
    for line in result.stderr.strip().splitlines():
        logger.debug(f"  [generator] {line}")

    if result.returncode != 0:
        logger.error(f"Generator exited with code {result.returncode}")
        return False

    start_str  = start_date.strftime('%Y-%m-%d')
    end_str    = end_date.strftime('%Y-%m-%d')
    report_dir = Path(__file__).parent / 'reports' / f'{start_str}_to_{end_str}'
    html_file  = report_dir / f'team_weekly_{start_str}_to_{end_str}.html'
    pdf_file   = report_dir / f'team_weekly_{start_str}_to_{end_str}.pdf'

    if not html_file.exists():
        logger.error(f"HTML report not found after generation: {html_file}")
        return False

    logger.info(f"HTML report ready: {html_file}")
    if pdf_file.exists():
        logger.info(f"PDF report ready : {pdf_file}")
    else:
        logger.warning("PDF not found — WeasyPrint may have failed")

    return True


def main():
    logger.info("=" * 60)
    logger.info("SentinelEdge Weekly Report Generator — START")
    logger.info(f"Run time        : {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
    logger.info(f"Server date/day : {date.today()} ({date.today().strftime('%A')})")

    start_date, end_date = get_last_week_dates()
    logger.info(f"Reporting week  : {start_date} to {end_date}")
    logger.info("=" * 60)

    success = generate_report(start_date, end_date)

    if success:
        cleanup_old_reports(keep_weeks=8)
        logger.info("Generation job completed successfully ✅")
    else:
        logger.error("Generation job failed ❌ — email dispatcher will detect this and skip send")
        sys.exit(1)


if __name__ == '__main__':
    main()
