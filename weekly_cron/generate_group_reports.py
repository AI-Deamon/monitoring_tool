#!/usr/bin/env python3
"""
Configurable Report Generator for SentinelEdge
Edit the USER_GROUP and REPORT_CONFIG below to customize reports.
"""

import os
import sys
import argparse
import logging
from datetime import datetime, timedelta, date
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURATION - Edit these values to customize your report
# ============================================================================

# List of usernames to generate reports for (case-insensitive matching)
USER_GROUP = [
    'Bindu',
    'Harish',
    'Abhilash',
    'surya',
    'sivaiah',
    'sanjana',
    'gopi'
]

# Report configuration
REPORT_CONFIG = {
    'type': 'monthly',           # 'weekly' or 'monthly'
    'month': '2026-03',          # Format: YYYY-MM (for monthly)
    # OR for weekly:
    # 'start_date': '2026-03-24',  # Format: YYYY-MM-DD
    # 'end_date': '2026-03-30',    # Format: YYYY-MM-DD
}

# Database URL (can also be set via --db-url flag)
DATABASE_URL = 'postgresql://sentinel_user:sentinel_secure_password_2024@localhost:5432/sentineledge'

# Output directory (optional, defaults to reports/)
OUTPUT_DIR = None

# ============================================================================
# SCRIPT LOGIC - Usually no need to edit below
# ============================================================================

def get_date_range(config):
    """Parse date range from config."""
    if 'month' in config:
        year, month = map(int, config['month'].split('-'))
        from calendar import monthrange
        _, last_day = monthrange(year, month)
        start_date = date(year, month, 1)
        end_date = date(year, month, last_day)
        return start_date, end_date
    elif 'start_date' in config and 'end_date' in config:
        return (
            datetime.strptime(config['start_date'], '%Y-%m-%d').date(),
            datetime.strptime(config['end_date'], '%Y-%m-%d').date()
        )
    else:
        today = date.today()
        days_since_monday = today.weekday()
        last_monday = today - timedelta(days=days_since_monday + 7)
        last_sunday = last_monday + timedelta(days=6)
        return last_monday, last_sunday


def main():
    parser = argparse.ArgumentParser(description='Generate reports for user group')
    parser.add_argument('--db-url', help='Database URL override')
    parser.add_argument('--output', '-o', help='Output directory override')
    parser.add_argument('--weekly', action='store_true', help='Generate weekly report')
    parser.add_argument('--monthly', action='store_true', help='Generate monthly report')
    parser.add_argument('--month', '-m', help='Month (YYYY-MM)')
    parser.add_argument('--start', '-s', help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', '-e', help='End date (YYYY-MM-DD)')
    parser.add_argument('--users', help='Override user group (comma-separated)')
    parser.add_argument('--team', '-t', action='store_true', help='Also generate team report')
    
    args = parser.parse_args()
    
    # Determine report type
    if args.weekly:
        report_type = 'weekly'
    elif args.monthly:
        report_type = 'monthly'
    else:
        report_type = REPORT_CONFIG.get('type', 'monthly')
    
    # Determine date range
    if args.month:
        year, month = map(int, args.month.split('-'))
        from calendar import monthrange
        _, last_day = monthrange(year, month)
        start_date = date(year, month, 1)
        end_date = date(year, month, last_day)
    elif args.start and args.end:
        start_date = datetime.strptime(args.start, '%Y-%m-%d').date()
        end_date = datetime.strptime(args.end, '%Y-%m-%d').date()
    else:
        start_date, end_date = get_date_range(REPORT_CONFIG)
    
    # Determine users
    if args.users:
        users = [u.strip() for u in args.users.split(',')]
    else:
        users = USER_GROUP
    
    # Database URL
    db_url = args.db_url or os.environ.get('DATABASE_URL') or DATABASE_URL
    if not db_url:
        logger.error("DATABASE_URL not provided")
        sys.exit(1)
    
    # Output directory
    output_dir = args.output or OUTPUT_DIR
    
    # Import and run the appropriate generator
    if report_type == 'monthly':
        from generate_monthly_reports import MonthlyReportGenerator
        Generator = MonthlyReportGenerator
        folder_prefix = 'monthly_'
    else:
        from generate_weekly_reports import WeeklyReportGenerator
        Generator = WeeklyReportGenerator
        folder_prefix = ''
    
    generator = Generator(db_url)
    
    if output_dir:
        generator.output_dir = Path(output_dir)
    
    try:
        generated_files = []
        
        # Generate individual reports
        logger.info(f"Generating {report_type} reports for {len(users)} users...")
        for username in users:
            files = generator.generate_for_user(username, start_date, end_date)
            generated_files.extend(files)
        
        # Generate team report if requested
        if args.team:
            logger.info("Generating team report...")
            team_files = generator.generate_team_report(start_date, end_date)
            generated_files.extend(team_files)
        
        if generated_files:
            logger.info(f"\n✅ Generated {len(generated_files)} report(s)")
            for f in generated_files:
                logger.info(f"   {f}")
        else:
            logger.warning("No reports generated")
    
    finally:
        generator.close()


if __name__ == '__main__':
    main()
