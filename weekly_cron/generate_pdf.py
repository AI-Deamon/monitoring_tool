#!/usr/bin/env python3
"""
Generate PDF from team_weekly_report_pdf.html template
"""
import sys
import os
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML

# FR-007: the single canonical date presentation, shared with the
# Flask app so cron-rendered reports match server-rendered ones.
try:
    from utils.datetime_format import format_date as _fmt_date
    from utils.datetime_format import format_datetime_seconds_labelled as _fmt_datetime_seconds_tz
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'server'))
    from utils.datetime_format import format_date as _fmt_date
    from utils.datetime_format import format_datetime_seconds_labelled as _fmt_datetime_seconds_tz

def main():
    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        print("DATABASE_URL not set")
        sys.exit(1)
    
    # Load the same data as generate_weekly_reports.py
    sys.path.insert(0, str(Path(__file__).parent))
    from generate_weekly_reports import WeeklyReportGenerator
    from generate_weekly_reports import get_all_active_usernames_data
    
    gen = WeeklyReportGenerator(db_url)
    from datetime import date, timedelta
    today = date.today()
    days_since_monday = today.weekday()
    last_monday = today - timedelta(days=days_since_monday + 7)
    last_sunday = last_monday + timedelta(days=6)
    
    start_str = last_monday.strftime('%Y-%m-%d')
    end_str = last_sunday.strftime('%Y-%m-%d')
    
    print(f"Generating PDF for {start_str} to {end_str}")
    
    data = gen.build_team_report_data(last_monday, last_sunday)
    
    if not data:
        print("No data generated")
        sys.exit(1)
    
    # Render PDF template
    template_dir = Path(__file__).parent / 'templates' / 'reports'
    env = Environment(loader=FileSystemLoader(str(template_dir)))
    env.filters['fmt_date'] = _fmt_date
    env.filters['fmt_datetime_seconds_tz'] = _fmt_datetime_seconds_tz
    template = env.get_template('team_weekly_report_pdf.html')
    
    output_dir = Path(__file__).parent / 'reports' / f"{start_str}_to_{end_str}"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    pdf_file = output_dir / f"team_weekly_{start_str}_to_{end_str}.pdf"
    
    html_content = template.render(**data)
    HTML(string=html_content).write_pdf(str(pdf_file))
    
    print(f"PDF saved: {pdf_file}")

if __name__ == '__main__':
    main()
