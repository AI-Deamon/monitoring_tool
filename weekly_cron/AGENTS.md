# weekly_cron - Agent Instructions

Standalone report generators that connect directly to PostgreSQL via `psycopg2`.
They do **not** use the Flask app or SQLAlchemy models.

## Environment Setup

All scripts load environment variables from the server `.env` file automatically:
```
/home/burpsuite/server/monitoring_tool-main_dev/monitoring_tool-main/server/.env
```

Required variables in `.env`:
```
# Database
DATABASE_URL=postgresql://sentinel_user:sentinel_secure_password_2024@localhost:5432/sentineledge

# SMTP (for send_report_email.py)
SMTP_HOST=smtp.office365.com
SMTP_PORT=587
SMTP_USER=noreply@yourcompany.com
SMTP_PASSWORD=<password>
SMTP_FROM_NAME=SentinelEdge Reports

# Report recipients (comma-separated)
REPORT_RECIPIENTS=alice@yourcompany.com,bob@yourcompany.com
REPORT_CC_RECIPIENTS=manager@yourcompany.com
```

Install dependency if not present:
```bash
pip3 install python-dotenv
```

---

## Cron Setup (production)

```
# Generate weekly team report at 8:00 AM every Monday
0 8 * * 1 cd /home/burpsuite/server/.../weekly_cron && python3 send_weekly_report.py

# Send email at 10:30 AM every Monday (after generation completes)
30 10 * * 1 cd /home/burpsuite/server/.../weekly_cron && python3 send_report_email.py
```

Edit with: `crontab -e`
Verify with: `crontab -l`

---

## Scripts

| Script | Purpose |
|---|---|
| `send_weekly_report.py` | Cron 1 — generates HTML + PDF, cleans up reports older than 8 weeks |
| `send_report_email.py` | Cron 2 — finds this week's files, freshness check, sends email |
| `generate_weekly_reports.py` | Core generator — fetches DB data, renders templates |
| `generate_monthly_reports.py` | Monthly report generator |
| `generate_daily_reports.py` | Daily report generator (requires `--agent-id`) |
| `generate_group_reports.py` | Batch generator for a configured list of users |
| `generate_pdf.py` | Standalone PDF generator from weekly data |

---

## Running Reports Manually

```bash
cd /home/burpsuite/server/.../weekly_cron

# Generate this week's team report
python3 send_weekly_report.py

# Send the email (after generation)
python3 send_report_email.py

# Generate for a specific date range
python3 generate_weekly_reports.py --team --start 2026-04-27 --end 2026-05-03

# Generate for a single user
python3 generate_weekly_reports.py --user surya --last-week

# Generate for multiple users
python3 generate_weekly_reports.py --users surya,chetan,anish --last-week

# Monthly report
python3 generate_monthly_reports.py --user surya --month 2026-04

# Daily report (needs agent UUID not username)
python3 generate_daily_reports.py --agent-id <uuid> --start 2026-05-01 --end 2026-05-03
```

---

## Logs

| Log file | What it covers |
|---|---|
| `logs/send_weekly_report.log` | Generation runs, DB warnings, PDF status |
| `logs/send_report_email.log` | File detection, freshness check, SMTP result |

```bash
# Check latest generation run
tail -30 logs/send_weekly_report.log

# Check latest email dispatch
tail -30 logs/send_report_email.log

# Watch both together
tail -20 logs/send_weekly_report.log logs/send_report_email.log
```

Logs rotate at 5 MB, keeping 4 backups.

---

## Output

Reports saved to: `reports/<start>_to_<end>/`
- `team_weekly_<start>_to_<end>.html`
- `team_weekly_<start>_to_<end>.pdf`

Old report folders (older than 8 weeks) are deleted automatically after each successful generation run.

---

## Templates

| Template | Used by |
|---|---|
| `templates/reports/team_weekly_report.html` | HTML email attachment |
| `templates/reports/team_weekly_report_pdf.html` | PDF attachment |
| `templates/reports/individual_weekly_report.html` | Per-user weekly report |
| `templates/reports/team_monthly_report.html` | Team monthly report |
| `templates/reports/individual_monthly_report.html` | Per-user monthly report |

---

## Troubleshooting

| Symptom | Where to look |
|---|---|
| Email not received | `logs/send_report_email.log` — check SMTP error |
| Report shows 0 active members | `logs/send_weekly_report.log` — look for SKIPPING warnings |
| Wrong week data | Check `Reporting week` line in log — verify server date with `date` |
| `.env` not loading | Run `python3 -c "from dotenv import load_dotenv; load_dotenv('../.env'); import os; print(os.environ.get('DATABASE_URL'))"` |
| PDF not generated | Look for `[ERROR] PDF generation failed` in generation log |
