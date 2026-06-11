"""
Report Engine - SentinelEdge
Generates weekly/monthly/daily/team HTML reports from DB and sends via SMTP.
"""
import os
import json
import smtplib
import logging
from datetime import timedelta, date, datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape

# IST timezone (UTC+5:30)
IST = timezone(timedelta(hours=5, minutes=30))

logger = logging.getLogger(__name__)

# ── Classification maps and helpers — imported from report_constants ──────────
from report_constants import (
    APP_CATEGORIES, APP_FRIENDLY_NAMES, DOMAIN_CATEGORIES, SYSTEM_APPS,
    get_category as _get_category,
    get_domain_category as _get_domain_category,
    friendly_name as _friendly,
    fmt_duration as _fmt_duration,
    fmt_hours as _fmt_hours,
)

TEMPLATE_DIR = Path(__file__).parent / 'templates' / 'reports'


def _make_jinja_env():
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(['html']),
    )
    env.filters['format_duration'] = _fmt_duration
    env.filters['format_hours'] = _fmt_hours
    return env


# ── DB queries (raw SQL via SQLAlchemy text) ──────────────────────────────────

def _query(db, sql, params):
    from sqlalchemy import text
    result = db.session.execute(text(sql), params)
    cols = result.keys()
    return [dict(zip(cols, row)) for row in result.fetchall()]


def _get_agent_info(db, agent_id):
    rows = _query(db, """
        SELECT a.agent_id::text, a.agent_name, a.hostname, a.os,
               acs.username
        FROM agents a
        LEFT JOIN agent_current_status acs ON a.agent_id = acs.agent_id
        WHERE a.agent_id = :aid
    """, {'aid': agent_id})
    return rows[0] if rows else {}


def _get_screen_time(db, agent_id, start, end):
    return _query(db, """
        SELECT date,
               COALESCE(active_seconds,0) as active_seconds,
               COALESCE(idle_seconds,0) as idle_seconds,
               COALESCE(locked_seconds,0) as locked_seconds,
               COALESCE(away_seconds,0) as away_seconds
        FROM screen_time
        WHERE agent_id = :aid AND date BETWEEN :s AND :e
        ORDER BY date
    """, {'aid': agent_id, 's': start, 'e': end})


def _get_app_usage(db, agent_id, start, end):
    return _query(db, """
        SELECT app, SUM(duration_seconds) as total_time, SUM(session_count) as sessions
        FROM app_usage
        WHERE agent_id = :aid AND date BETWEEN :s AND :e
        GROUP BY app HAVING SUM(duration_seconds) > 0
        ORDER BY total_time DESC LIMIT 20
    """, {'aid': agent_id, 's': start, 'e': end})


def _get_domain_usage(db, agent_id, start, end):
    return _query(db, """
        SELECT domain, SUM(duration_seconds) as total_time, SUM(session_count) as visits
        FROM domain_usage
        WHERE agent_id = :aid AND date BETWEEN :s AND :e
        GROUP BY domain HAVING SUM(duration_seconds) > 0
        ORDER BY total_time DESC LIMIT 20
    """, {'aid': agent_id, 's': start, 'e': end})


def _get_inventory_changes(db, agent_id, start, end):
    return _query(db, """
        SELECT change_type, app_name, version, timestamp
        FROM app_inventory_changes
        WHERE agent_id = :aid AND DATE(timestamp) BETWEEN :s AND :e
        ORDER BY timestamp DESC
    """, {'aid': agent_id, 's': start, 'e': end})


def _get_active_agents(db):
    return _query(db, """
        SELECT DISTINCT a.agent_id::text, a.agent_name, a.hostname, acs.username
        FROM agents a
        JOIN agent_current_status acs ON a.agent_id = acs.agent_id
        WHERE a.status = 'active' AND acs.username IS NOT NULL
        ORDER BY acs.username
    """, {})


def _agg_screen_time(rows):
    ta = sum(r['active_seconds'] for r in rows)
    ti = sum(r['idle_seconds'] for r in rows)
    tl = sum(r['locked_seconds'] for r in rows)
    tw = sum(r['away_seconds'] for r in rows)
    days = len([r for r in rows if r['active_seconds'] > 0])
    return {
        'total_active': ta, 'total_idle': ti,
        'total_locked': tl, 'total_away': tw,
        'total': ta + ti + tl + tw,
        'days_worked': days,
        'avg_daily': ta / days if days else 0,
        'daily_breakdown': rows,
    }


def _process_apps(raw):
    out = []
    for r in raw:
        if (r['app'] or '').lower() in SYSTEM_APPS:
            continue
        out.append({
            'app': r['app'],
            'friendly_name': _friendly(r['app']),
            'category': _get_category(r['app']),
            'total_time': r['total_time'],
            'sessions': r['sessions'],
            'duration': _fmt_duration(r['total_time']),
            'hours': _fmt_hours(r['total_time']),
        })
    return out


def _process_domains(raw):
    return [{
        'domain': r['domain'],
        'category': _get_domain_category(r['domain']),
        'total_time': r['total_time'],
        'visits': r['visits'],
        'duration': _fmt_duration(r['total_time']),
        'hours': _fmt_hours(r['total_time']),
    } for r in raw]


# ── Public API ────────────────────────────────────────────────────────────────

def build_individual_report(db, agent_id, start_date, end_date):
    """Return context dict for individual weekly/monthly report."""
    agent_info = _get_agent_info(db, agent_id)
    if not agent_info:
        return None

    username = agent_info.get('username', 'Unknown')
    if '\\' in (username or ''):
        username = username.split('\\')[-1]

    st_rows = _get_screen_time(db, agent_id, start_date, end_date)
    apps = _process_apps(_get_app_usage(db, agent_id, start_date, end_date))
    domains = _process_domains(_get_domain_usage(db, agent_id, start_date, end_date))
    changes = _get_inventory_changes(db, agent_id, start_date, end_date)
    screen_time = _agg_screen_time(st_rows)

    highest = max(st_rows, key=lambda x: x['active_seconds']) if st_rows else None
    active_days = [d for d in st_rows if d['active_seconds'] > 0]
    lowest = min(active_days, key=lambda x: x['active_seconds']) if active_days else None

    return {
        'agent_info': agent_info,
        'username': username,
        'start_date': start_date,
        'end_date': end_date,
        'generated_at': datetime.now(IST),
        'screen_time': screen_time,
        'apps': apps,
        'domains': domains,
        'new_installs': [c for c in changes if c['change_type'] == 'installed'],
        'uninstalls': [c for c in changes if c['change_type'] == 'uninstalled'],
        'highest_day': highest,
        'lowest_day': lowest,
    }


def build_team_report(db, start_date, end_date, on_progress=None):
    """Return context dict for team weekly/monthly report."""
    agents = _get_active_agents(db)
    members = []
    total_active = 0
    total = len(agents)

    for i, agent in enumerate(agents):
        if on_progress:
            on_progress(i + 1, total, agent.get('username', agent['agent_id']))
        ctx = build_individual_report(db, agent['agent_id'], start_date, end_date)
        if ctx and ctx['screen_time']['days_worked'] > 0:
            members.append(ctx)
            total_active += ctx['screen_time']['total_active']

    members.sort(key=lambda x: x['screen_time']['total_active'], reverse=True)

    # Aggregate team apps
    all_apps = {}
    for m in members:
        for app in m['apps'][:15]:
            k = (app['app'], app['friendly_name'], app['category'])
            if k not in all_apps:
                all_apps[k] = {'hours': 0, 'sessions': 0}
            all_apps[k]['hours'] += app['total_time']
            all_apps[k]['sessions'] += app['sessions']

    top_apps = [
        {'app': k[0], 'friendly_name': k[1], 'category': k[2],
         'hours': _fmt_hours(v['hours']), 'duration': _fmt_duration(v['hours']),
         'sessions': v['sessions']}
        for k, v in sorted(all_apps.items(), key=lambda x: x[1]['hours'], reverse=True)[:15]
    ]

    # Aggregate team domains
    all_domains = {}
    for m in members:
        for d in m['domains'][:15]:
            k = d['domain']
            if k not in all_domains:
                all_domains[k] = {'hours': 0, 'visits': 0, 'category': d['category']}
            all_domains[k]['hours'] += d['total_time']
            all_domains[k]['visits'] += d['visits']

    top_domains = [
        {'domain': k, 'category': v['category'],
         'hours': _fmt_hours(v['hours']), 'duration': _fmt_duration(v['hours']),
         'visits': v['visits']}
        for k, v in sorted(all_domains.items(), key=lambda x: x[1]['hours'], reverse=True)[:15]
    ]

    # Daily totals
    n_days = (end_date - start_date).days + 1
    daily = {i: {'active': 0, 'idle': 0, 'locked': 0} for i in range(n_days)}
    for m in members:
        for day in m['screen_time']['daily_breakdown']:
            idx = (day['date'] - start_date).days
            if 0 <= idx < n_days:
                daily[idx]['active'] += day['active_seconds']
                daily[idx]['idle'] += day['idle_seconds']
                daily[idx]['locked'] += day['locked_seconds']

    daily_totals = [
        {'day': (start_date + timedelta(days=i)).strftime('%A'),
         'date': (start_date + timedelta(days=i)).strftime('%Y-%m-%d'),
         **daily[i]}
        for i in range(n_days)
    ]

    return {
        'start_date': start_date,
        'end_date': end_date,
        'generated_at': datetime.now(IST),
        'team_members': members,
        'total_team_hours': _fmt_hours(total_active),
        'avg_per_member': _fmt_hours(total_active / len(members)) if members else 0,
        'active_members': len(members),
        'top_team_apps': top_apps,
        'top_team_domains': top_domains,
        'daily_totals': daily_totals,
    }


def render_report_html(report_type, scope, context):
    """Render report to HTML string using Jinja2 templates from tests/reports/."""
    env = _make_jinja_env()
    template_map = {
        ('weekly', 'team'):       'team_weekly_report.html',
        ('monthly', 'team'):      'team_monthly_report.html',
        ('weekly', 'individual'): 'individual_weekly_report.html',
        ('monthly', 'individual'):'individual_monthly_report.html',
        ('daily', 'individual'):  'individual_weekly_report.html',  # reuse weekly layout
    }
    tpl_name = template_map.get((report_type, scope), 'individual_weekly_report.html')
    return env.get_template(tpl_name).render(**context)


def send_report_email(html_content, recipients, subject, cc=None):
    """Send HTML report via noreply SMTP. Returns (success, error_msg)."""
    smtp_host = os.environ.get('SMTP_HOST', 'smtp.office365.com')
    smtp_port = int(os.environ.get('SMTP_PORT', 587))
    smtp_user = os.environ.get('SMTP_USER', '')
    smtp_pass = os.environ.get('SMTP_PASSWORD', '')
    from_name = os.environ.get('SMTP_FROM_NAME', 'SentinelEdge Reports')

    if not smtp_user or not smtp_pass:
        logger.warning("[REPORTS] send_report_email: SMTP_USER/SMTP_PASSWORD not configured")
        return False, 'SMTP credentials not configured'

    msg = MIMEMultipart('alternative')
    msg['From'] = f'{from_name} <{smtp_user}>'
    msg['To'] = ', '.join(recipients) if isinstance(recipients, list) else recipients
    if cc:
        msg['Cc'] = ', '.join(cc) if isinstance(cc, list) else cc
    msg['Subject'] = subject
    msg.attach(MIMEText(html_content, 'html', 'utf-8'))

    all_rcpt = list(recipients) if isinstance(recipients, list) else [recipients]
    if cc:
        all_rcpt += list(cc) if isinstance(cc, list) else [cc]

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, all_rcpt, msg.as_string())
        logger.info(f"[REPORTS] Email sent: {subject} -> {all_rcpt}")
        return True, None
    except Exception as e:
        logger.error(f"[REPORTS] Email failed: {e}")
        return False, str(e)



# ── Async Job CRUD ────────────────────────────────────────────────────────────
def generate_pdf(html_content, output_path):
    """Generate PDF from HTML using WeasyPrint. Returns (success, path_or_error)."""
    try:
        from weasyprint import HTML
        HTML(string=html_content).write_pdf(str(output_path))
        return True, str(output_path)
    except ImportError:
        logger.warning("[REPORTS] WeasyPrint not installed — PDF generation skipped")
        return False, "WeasyPrint not installed"
    except Exception as e:
        logger.error(f"[REPORTS] PDF generation failed: {e}")
        return False, str(e)


def build_unified_report(db, report_type, scope, agent_id=None, start_date=None,
                         end_date=None, include_pdf=False, include_inventory=True,
                         frequency=None):
    """Build report with unified parameters. Wraps build_team/individual report.
    Returns (context_dict, pdf_path_or_None).
    """
    if start_date is None or end_date is None:
        from server_reports import _get_date_range
        start_date, end_date = _get_date_range(report_type, frequency or report_type)

    if scope == 'team':
        ctx = build_team_report(db, start_date, end_date)
    else:
        ctx = build_individual_report(db, agent_id, start_date, end_date)

    if not ctx:
        return None, None

    html = render_report_html(report_type, scope, ctx)
    pdf_path = None

    if include_pdf and scope == 'team' and report_type == 'weekly':
        import tempfile, os
        tmp = tempfile.NamedTemporaryFile(
            suffix='.pdf', prefix=f'sentineledge_{report_type}_{scope}_',
            delete=False, dir=tempfile.gettempdir()
        )
        tmp.close()
        ok, result = generate_pdf(html, tmp.name)
        if ok:
            pdf_path = result
        else:
            os.unlink(tmp.name)

    ctx['_html'] = html
    return ctx, pdf_path


import uuid as _uuid


def create_job(db, report_type, scope, agent_id, start_date, end_date, created_by=None, schedule_id=None):
    from server_models import ReportGenerationJob
    job_id = str(_uuid.uuid4())
    job = ReportGenerationJob(
        id=job_id, schedule_id=schedule_id, report_type=report_type,
        scope=scope, agent_id=agent_id, start_date=start_date,
        end_date=end_date, status='pending', progress={}, created_by=created_by,
    )
    db.session.add(job)
    db.session.commit()
    return job_id


def update_job_progress(db, job_id, current, total, current_agent):
    from server_models import ReportGenerationJob
    job = db.session.get(ReportGenerationJob, job_id)
    if job:
        job.status = 'running'
        job.progress = {'current': current, 'total': total, 'current_agent': current_agent}
        db.session.commit()


def complete_job(db, job_id, html):
    from server_models import ReportGenerationJob
    job = db.session.get(ReportGenerationJob, job_id)
    if job:
        job.status = 'completed'
        job.result_html = html
        job.completed_at = datetime.now(timezone.utc)
        db.session.commit()


def fail_job(db, job_id, error):
    from server_models import ReportGenerationJob
    job = db.session.get(ReportGenerationJob, job_id)
    if job:
        job.status = 'failed'
        job.error_message = str(error)
        job.completed_at = datetime.now(timezone.utc)
        db.session.commit()


def get_job(db, job_id):
    from server_models import ReportGenerationJob
    job = db.session.get(ReportGenerationJob, job_id)
    if not job:
        return None
    return {
        'job_id': job.id,
        'status': job.status,
        'progress': job.progress or {},
        'result_html': job.result_html,
        'result_pdf_path': job.result_pdf_path,
        'error_message': job.error_message,
        'created_at': job.created_at.isoformat() if job.created_at else None,
        'completed_at': job.completed_at.isoformat() if job.completed_at else None,
    }


def run_report_job(app, db, job_id, report_type, scope, agent_id, start_date, end_date, auto_email=False, recipients=None, include_pdf=False):
    """Run report generation synchronously. Caller is responsible for running in a background thread."""
    try:
        update_job_progress(db, job_id, 0, 1, 'starting')

        def on_progress(current, total, agent_name):
            update_job_progress(db, job_id, current, total, agent_name)

        if scope == 'team':
            ctx = build_team_report(db, start_date, end_date, on_progress=on_progress)
        else:
            ctx = build_individual_report(db, agent_id, start_date, end_date)

        if not ctx:
            fail_job(db, job_id, 'No data found for the selected period')
            return

        html = render_report_html(report_type, scope, ctx)

        # PDF generation
        pdf_path = None
        if include_pdf:
            import tempfile, os
            tmp = tempfile.NamedTemporaryFile(
                suffix='.pdf', prefix=f'sentineledge_{report_type}_{scope}_',
                delete=False, dir=tempfile.gettempdir()
            )
            tmp.close()
            ok, result = generate_pdf(html, tmp.name)
            if ok:
                pdf_path = result
            else:
                try:
                    os.unlink(tmp.name)
                except Exception:
                    pass

        # Save job result
        from server_models import ReportGenerationJob
        job = db.session.get(ReportGenerationJob, job_id)
        if job:
            job.status = 'completed'
            job.result_html = html
            job.result_pdf_path = pdf_path
            job.completed_at = datetime.now(timezone.utc)
            db.session.commit()

        if auto_email and recipients:
            subject = f"SentinelEdge {report_type.title()} {scope.title()} Report \u2014 {start_date} to {end_date}"
            ok, err = send_report_email(html, recipients, subject)
            if not ok:
                logger.warning(f"[REPORTS] Job {job_id}: email failed — {err}")
                job = db.session.get(ReportGenerationJob, job_id)
                if job:
                    job.error_message = f"Report generated but email failed: {err}"
                    db.session.commit()

    except Exception as e:
        logger.exception(f"[REPORTS] Job {job_id} failed: {e}")
        fail_job(db, job_id, str(e))
