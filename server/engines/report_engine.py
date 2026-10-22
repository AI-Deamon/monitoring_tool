"""
Report Engine - SentinelEdge
Generates weekly/monthly/daily/team HTML reports from DB and sends via SMTP.
"""
import os
import json
import uuid
import shutil
import smtplib
import logging
from contextlib import nullcontext
from datetime import timedelta, date, datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape
from utils.dt import utcnow_naive

from engines.report_naming import (
    build_report_filename,
    build_report_metadata,
    sanitize_identity,
    format_period,
    parse_report_filename,
    get_reports_storage_dir,
    resolve_collision_safe_path,
    safe_write_file,
)

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

TEMPLATE_DIR = Path(__file__).parent.parent / 'templates' / 'reports'


def _make_jinja_env():
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(['html']),
    )
    env.filters['format_duration'] = _fmt_duration
    env.filters['format_hours'] = _fmt_hours

    # FR-007: the single canonical date presentation. Report templates carried
    # seven competing strftime formats between them ('%B %d, %Y',
    # '%Y-%m-%d at %H:%M', '%A, %B %d', '%d-%m-%Y %I:%M %p' and more), which is
    # the same missing-abstraction problem the dashboard had.
    from utils.datetime_format import format_date as _fmt_date
    from utils.datetime_format import format_datetime as _fmt_datetime
    env.filters['fmt_date'] = _fmt_date
    env.filters['fmt_datetime'] = _fmt_datetime
    from utils.datetime_format import format_datetime_labelled as _fmt_dt_lbl
    env.filters['fmt_datetime_tz'] = _fmt_dt_lbl
    from utils.datetime_format import format_datetime_seconds as _fmt_dt_s
    env.filters['fmt_datetime_seconds'] = _fmt_dt_s
    from utils.datetime_format import format_datetime_seconds_labelled as _fmt_dt_s_lbl
    env.filters['fmt_datetime_seconds_tz'] = _fmt_dt_s_lbl

    # Report templates share the CSP hardening applied to dashboard templates and
    # call csp_nonce() on inline <style>/<script> tags. In a request, that global
    # comes from the Flask context processor in server_app.py. This environment is
    # standalone — reports are rendered for email and PDF outside any request — so
    # the global is absent and every render raises UndefinedError.
    #
    # This is defect D12 ("Not able to generate the report"): the failure is total
    # and affects every report type, because all five templates call it.
    #
    # An empty nonce is the correct value here, not a workaround: the output is a
    # standalone document, not a response served under a CSP header, so there is no
    # policy for a nonce to match. Emitting nonce="" keeps the markup valid and the
    # template shared between both paths.
    env.globals['csp_nonce'] = lambda: ''

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
    rows = _query(db, """
        SELECT date,
               COALESCE(active_seconds,0) as active_seconds,
               COALESCE(idle_seconds,0) as idle_seconds,
               COALESCE(locked_seconds,0) as locked_seconds,
               COALESCE(away_seconds,0) as away_seconds
        FROM screen_time
        WHERE agent_id = :aid AND date BETWEEN :s AND :e
        ORDER BY date
    """, {'aid': agent_id, 's': start, 'e': end})
    #added for idel time disable functionality
    for r in rows:
        r['active_seconds'] = (r.get('active_seconds') or 0) + (r.get('idle_seconds') or 0)
        r['idle_seconds'] = 0
    return rows


def _get_app_usage(db, agent_id, start, end):
    return _query(db, """
        SELECT app, SUM(duration_seconds) as total_time, SUM(session_count) as sessions
        FROM app_usage
        WHERE agent_id = :aid AND date BETWEEN :s AND :e
          AND EXTRACT(DOW FROM date) BETWEEN 1 AND 5
        GROUP BY app HAVING SUM(duration_seconds) > 0
        ORDER BY total_time DESC LIMIT 20
    """, {'aid': agent_id, 's': start, 'e': end})


def _get_domain_usage(db, agent_id, start, end):
    return _query(db, """
        SELECT domain, SUM(duration_seconds) as total_time, SUM(session_count) as visits
        FROM domain_usage
        WHERE agent_id = :aid AND date BETWEEN :s AND :e
          AND EXTRACT(DOW FROM date) BETWEEN 1 AND 5
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


def _is_weekday(date_obj):
    """Check if date is a weekday (Monday=0 to Friday=4)."""
    return date_obj.weekday() < 5


def _agg_screen_time(rows):
    # Filter for weekdays only (Monday-Friday)
    weekday_rows = [r for r in rows if _is_weekday(r['date'])]
    
    ta = sum(r['active_seconds'] for r in weekday_rows)
    ti = sum(r['idle_seconds'] for r in weekday_rows)
    tl = sum(r['locked_seconds'] for r in weekday_rows)
    tw = sum(r['away_seconds'] for r in weekday_rows)
    days = len([r for r in weekday_rows if r['active_seconds'] > 0])
    return {
        'total_active': ta, 'total_idle': ti,
        'total_locked': tl, 'total_away': tw,
        'total': ta + ti + tl + tw,
        'days_worked': days,
        'avg_daily': ta / days if days else 0,
        'daily_breakdown': weekday_rows,
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

    # Daily totals (weekdays only)
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
        if _is_weekday(start_date + timedelta(days=i))
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
        ('daily', 'team'):        'team_weekly_report.html',        # reuse weekly layout
        ('weekly', 'individual'): 'individual_weekly_report.html',
        ('monthly', 'individual'):'individual_monthly_report.html',
        ('daily', 'individual'):  'individual_weekly_report.html',  # reuse weekly layout
    }
    tpl_name = template_map.get((report_type, scope))
    if tpl_name is None:
        # Previously defaulted to the individual template here, which silently
        # rendered team-shaped context (no 'agent_info' key) through a template
        # that requires it — crashed as UndefinedError instead of a clear
        # "unsupported combination" failure. Fail loudly instead.
        raise ValueError(f"{REASON_UNKNOWN_SCOPE} (report_type={report_type!r}, scope={scope!r})")
    return env.get_template(tpl_name).render(**context)


def validate_attachments(attachments):
    """Validate attachments list, filtering out non-existent, empty, or unreadable files.
    Returns a list of validated attachment dicts with 'path'/'content', 'filename', and 'content_type'.
    """
    if not attachments:
        return []

    validated = []
    for att in attachments:
        if not isinstance(att, dict):
            continue

        path = att.get('path')
        content = att.get('content')
        filename = att.get('filename') or (os.path.basename(path) if path else 'attachment')
        content_type = att.get('content_type') or att.get('mimetype')
        if not content_type:
            lower_fn = filename.lower()
            if lower_fn.endswith('.pdf'):
                content_type = 'application/pdf'
            elif lower_fn.endswith('.html') or lower_fn.endswith('.htm'):
                content_type = 'text/html'
            else:
                content_type = 'application/octet-stream'

        if path:
            if not os.path.exists(path):
                continue
            try:
                if os.path.getsize(path) <= 0:
                    continue
            except OSError:
                continue
            validated.append({
                'path': str(path),
                'filename': filename,
                'content_type': content_type,
            })
        elif content is not None:
            if len(content) == 0:
                continue
            validated.append({
                'content': content,
                'filename': filename,
                'content_type': content_type,
            })

    return validated


def describe_attachments(attachments):
    """Describe attachments for email body presentation."""
    if not attachments:
        return {
            "attachment_type": "none",
            "description": "No report files are attached."
        }

    has_pdf = False
    has_html = False
    for att in attachments:
        fn = (att.get('filename') or att.get('path') or '').lower()
        ct = (att.get('content_type') or att.get('mimetype') or '').lower()
        if fn.endswith('.pdf') or ct == 'application/pdf':
            has_pdf = True
        if fn.endswith('.html') or fn.endswith('.htm') or ct == 'text/html':
            has_html = True

    if has_pdf and has_html:
        return {
            "attachment_type": "both",
            "description": "Both HTML and PDF versions are included for ease of review."
        }
    elif has_pdf:
        return {
            "attachment_type": "pdf",
            "description": "A PDF version is included for ease of review."
        }
    elif has_html:
        return {
            "attachment_type": "html",
            "description": "An HTML version is included for ease of review."
        }
    else:
        return {
            "attachment_type": "other",
            "description": "Report attachments are included for ease of review."
        }


def render_email_body_html(*args, **kwargs):
    """Render HTML email body from email_body_template.html.
    Supports positional: (report_type, scope, start_str, end_str)
    or keyword arguments / metadata dict.
    """
    try:
        env = _make_jinja_env()
        meta = kwargs.get('metadata') or {}

        # Extract parameters with fallbacks
        report_type = kwargs.get('report_type') or meta.get('report_type')
        if not report_type and len(args) > 0:
            report_type = args[0]

        scope = kwargs.get('scope') or meta.get('scope')
        if not scope and len(args) > 1:
            scope = args[1]

        start_date = kwargs.get('start_date') or kwargs.get('start_str') or meta.get('start_date') or meta.get('start_str')
        if not start_date and len(args) > 2:
            start_date = args[2]

        end_date = kwargs.get('end_date') or kwargs.get('end_str') or meta.get('end_date') or meta.get('end_str')
        if not end_date and len(args) > 3:
            end_date = args[3]

        start_str = str(start_date) if start_date else ''
        end_str = str(end_date) if end_date else ''

        report_title = kwargs.get('report_title') or meta.get('report_title')
        if not report_title:
            if report_type and scope:
                report_title = f"{report_type.title()} {scope.title()} Activity Report"
            elif report_type:
                report_title = f"{report_type.title()} Activity Report"
            elif scope:
                report_title = f"{scope.title()} Activity Report"
            else:
                report_title = "Activity Report"

        period = kwargs.get('period') or meta.get('period')
        if period:
            period_display = str(period)
        elif start_str and end_str:
            period_display = f"{start_str} to {end_str}"
        elif start_str or end_str:
            period_display = start_str or end_str
        else:
            period_display = "N/A"

        agent_name = kwargs.get('agent_name') or meta.get('agent_name')
        team_name = kwargs.get('team_name') or meta.get('team_name')
        support_contact = kwargs.get('support_contact') or meta.get('support_contact')

        generated_at = (
            kwargs.get('generated_at') or kwargs.get('generated_at_utc') or
            meta.get('generated_at') or meta.get('generated_at_utc')
        )
        generated_at_display = str(generated_at) if generated_at else "N/A"

        report_type_display = report_type.title() if report_type else "N/A"
        scope_display = scope.title() if scope else "N/A"

        attachments = kwargs.get('attachments') if 'attachments' in kwargs else meta.get('attachments')
        if attachments is not None:
            valid_atts = validate_attachments(attachments)
            desc_info = describe_attachments(valid_atts)
        else:
            desc_info = describe_attachments(None)
        attachment_desc = desc_info["description"]

        return env.get_template('email_body_template.html').render(
            report_title=report_title,
            report_type_display=report_type_display,
            scope_display=scope_display,
            agent_name=agent_name,
            team_name=team_name,
            period_display=period_display,
            generated_at_display=generated_at_display,
            attachment_desc=attachment_desc,
            support_contact=support_contact,
            start_str=start_str,
            end_str=end_str,
        )
    except Exception as e:
        logger.warning(f"[REPORTS] Could not render HTML email body template: {e}")
        return None


def send_report_email(html_content, recipients, subject, cc=None, body_text=None,
                      attachments=None, report_type=None, scope=None,
                      start_date=None, end_date=None, pdf_path=None):
    """Send report email via SMTP.
    Supports sending as attachments with plain text and HTML body, or HTML body if body_text is None.
    """
    from email.mime.base import MIMEBase
    from email import encoders

    smtp_host = os.environ.get('SMTP_HOST', 'smtp.office365.com')
    smtp_port = int(os.environ.get('SMTP_PORT', 587))
    smtp_user = os.environ.get('SMTP_USER', '')
    smtp_pass = os.environ.get('SMTP_PASSWORD', '')
    from_name = os.environ.get('SMTP_FROM_NAME', 'SentinelEdge Reports')

    if not smtp_user or not smtp_pass:
        logger.warning("[REPORTS] send_report_email: SMTP_USER/SMTP_PASSWORD not configured")
        return False, 'SMTP credentials not configured'

    is_attachment_mode = (attachments is not None or start_date is not None or pdf_path is not None or body_text is not None)

    if not is_attachment_mode:
        msg = MIMEMultipart('alternative')
        msg['From'] = f'{from_name} <{smtp_user}>'
        msg['To'] = ', '.join(recipients) if isinstance(recipients, list) else recipients
        if cc:
            msg['Cc'] = ', '.join(cc) if isinstance(cc, list) else cc
        msg['Subject'] = subject
        msg.attach(MIMEText(html_content, 'html', 'utf-8'))
    else:
        if attachments is not None:
            validated_attachments = validate_attachments(attachments)
            if len(attachments) > 0 and len(validated_attachments) == 0:
                logger.warning("[REPORTS] send_report_email: No valid attachments found")
                return False, 'No valid attachments found'
        else:
            start_str = str(start_date) if start_date else ''
            end_str = str(end_date) if end_date else ''
            r_type = (report_type or 'weekly').lower()
            s_scope = (scope or 'team').lower()
            prefix = f"{s_scope}_{r_type}_{start_str}_to_{end_str}" if (start_str and end_str) else "sentineledge_report"
            auto_atts = []
            if html_content:
                auto_atts.append({
                    'filename': f"{prefix}.html",
                    'content': html_content.encode('utf-8') if isinstance(html_content, str) else html_content,
                    'content_type': 'text/html',
                })
            if pdf_path and os.path.exists(pdf_path):
                auto_atts.append({
                    'path': str(pdf_path),
                    'filename': os.path.basename(str(pdf_path)),
                    'content_type': 'application/pdf',
                })
            elif html_content:
                import tempfile
                tmp = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
                tmp.close()
                ok_pdf, res_pdf = generate_pdf(html_content, tmp.name)
                if ok_pdf and os.path.exists(res_pdf):
                    try:
                        with open(res_pdf, 'rb') as f:
                            auto_atts.append({
                                'filename': f"{prefix}.pdf",
                                'content': f.read(),
                                'content_type': 'application/pdf',
                            })
                    except Exception:
                        pass
                    finally:
                        try:
                            os.unlink(res_pdf)
                        except Exception:
                            pass
            validated_attachments = validate_attachments(auto_atts)

        msg = MIMEMultipart('mixed')
        msg['From'] = f'{from_name} <{smtp_user}>'
        msg['To'] = ', '.join(recipients) if isinstance(recipients, list) else recipients
        if cc:
            msg['Cc'] = ', '.join(cc) if isinstance(cc, list) else cc
        msg['Subject'] = subject

        start_str = str(start_date) if start_date else ''
        end_str = str(end_date) if end_date else ''
        r_type = (report_type or 'weekly').title()
        s_scope = (scope or 'team').title()

        if body_text is None:
            body_text = f"""Good Morning Team,

Please find attached the {r_type} {s_scope} Activity Report for the period {start_str} to {end_str}.
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

        body_alt = MIMEMultipart('alternative')
        body_alt.attach(MIMEText(body_text, 'plain'))

        if html_content and ('email-container' in html_content or 'meta-table' in html_content):
            body_html = html_content
        else:
            body_html = render_email_body_html(
                report_type=report_type,
                scope=scope,
                start_date=start_date,
                end_date=end_date,
                attachments=validated_attachments,
            )
            if not body_html:
                body_html = html_content

        if body_html:
            body_alt.attach(MIMEText(body_html, 'html', 'utf-8'))

        msg.attach(body_alt)

        for att in validated_attachments:
            filename = att.get('filename') or 'attachment'
            content_type = att.get('content_type') or 'application/octet-stream'
            main_type, sub_type = content_type.split('/', 1) if '/' in content_type else ('application', 'octet-stream')

            part = MIMEBase(main_type, sub_type)
            if att.get('path'):
                with open(att['path'], 'rb') as f:
                    part.set_payload(f.read())
            elif att.get('content'):
                raw_c = att['content']
                if isinstance(raw_c, str):
                    raw_c = raw_c.encode('utf-8')
                part.set_payload(raw_c)
            else:
                continue

            encoders.encode_base64(part)
            part.add_header('Content-Disposition', f'attachment; filename="{filename}"')
            msg.attach(part)

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
    """Generate PDF from HTML using WeasyPrint. Returns (success, path_or_error).
    Writes to a collision-safe path using an atomic temporary file, and cleans up on failure.
    """
    dest = resolve_collision_safe_path(output_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest.parent / f"{dest.name}.tmp.{uuid.uuid4().hex[:6]}"

    try:
        # Silence verbose WeasyPrint & fontTools subsetting logs
        logging.getLogger('fontTools').setLevel(logging.ERROR)
        logging.getLogger('weasyprint').setLevel(logging.ERROR)
        from weasyprint import HTML
        HTML(string=html_content).write_pdf(str(tmp_path))
        if not tmp_path.exists() or tmp_path.stat().st_size == 0:
            raise IOError("Generated PDF file is empty or missing")
        shutil.move(str(tmp_path), str(dest))
        return True, str(dest)
    except ImportError:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass
        logger.warning("[REPORTS] WeasyPrint not installed — PDF generation skipped")
        return False, "WeasyPrint not installed"
    except Exception as e:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass
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
        identity = 'team'
    else:
        ctx = build_individual_report(db, agent_id, start_date, end_date)
        agent_info = _get_agent_info(db, agent_id) if agent_id else {}
        identity = agent_info.get('agent_name') or agent_info.get('hostname') or agent_info.get('username') or agent_id

    if not ctx:
        return None, None

    html = render_report_html(report_type, scope, ctx)
    pdf_path = None

    if include_pdf:
        filename = build_report_filename(
            report_type=report_type,
            scope=scope,
            identity=identity,
            start_date=start_date,
            end_date=end_date,
            ext='pdf',
        )
        target_path = get_reports_storage_dir() / filename
        ok, result = generate_pdf(html, target_path)
        if ok:
            pdf_path = result

    ctx['_html'] = html
    return ctx, pdf_path

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
        job.completed_at = utcnow_naive()  # D02 / FR-009: naive UTC column
        db.session.commit()


def fail_job(db, job_id, error):
    from server_models import ReportGenerationJob
    job = db.session.get(ReportGenerationJob, job_id)
    if job:
        job.status = 'failed'
        job.error_message = str(error)
        job.completed_at = utcnow_naive()  # D02 / FR-009: naive UTC column
        db.session.commit()


def get_job(db, job_id):
    from server_models import ReportGenerationJob
    job = db.session.get(ReportGenerationJob, job_id)
    if not job:
        return None
    return {
        'job_id': job.id,
        'report_type': job.report_type,
        'scope': job.scope,
        'agent_id': job.agent_id,
        'start_date': job.start_date.isoformat() if job.start_date else None,
        'end_date': job.end_date.isoformat() if job.end_date else None,
        'status': job.status,
        'progress': job.progress or {},
        'result_html': job.result_html,
        'result_pdf_path': job.result_pdf_path,
        'error_message': job.error_message,
        'created_at': job.created_at.isoformat() if job.created_at else None,
        'completed_at': job.completed_at.isoformat() if job.completed_at else None,
    }


# Report failure reasons (feature 037, FR-021).
#
# These were previously one message — "No data found for the selected period" —
# used for every unsuccessful outcome. An agent that does not exist and an agent
# with a genuinely quiet week produced identical text, so a user could not tell
# a mistake from an empty week. FR-021 requires a specific stated reason.
REASON_AGENT_NOT_FOUND = (
    "That agent could not be found. It may have been removed, or you may not "
    "have access to it."
)
REASON_NO_DATA = (
    "No activity was recorded for the selected period."
)
REASON_UNKNOWN_SCOPE = "That report scope is not recognised."


def run_report_job(app, db, job_id, report_type, scope, agent_id, start_date, end_date, auto_email=False, recipients=None, include_pdf=False):
    """Run report generation synchronously. Caller is responsible for running in a background thread.

    `app` is the real Flask app when called from a raw Thread (e.g. the
    unified_generate endpoint) -- that thread has no app context of its own,
    so we push one here. When called from the scheduler (background_tasks.py),
    `app` is None because the caller already runs inside a pushed context.
    """
    with (app.app_context() if app is not None else nullcontext()):
        try:
            update_job_progress(db, job_id, 0, 1, 'starting')

            def on_progress(current, total, agent_name):
                update_job_progress(db, job_id, current, total, agent_name)

            if scope == 'team':
                ctx = build_team_report(db, start_date, end_date, on_progress=on_progress)
            else:
                ctx = build_individual_report(db, agent_id, start_date, end_date)

            if not ctx:
                # FR-021: name the actual cause. build_individual_report returns
                # None only when the agent itself cannot be found — an agent with no
                # activity still returns a context and renders an empty-state report
                # (FR-022), so reaching here for an individual scope means the agent
                # is missing, not that the week was quiet.
                reason = REASON_AGENT_NOT_FOUND if scope != 'team' else REASON_NO_DATA
                fail_job(db, job_id, reason)
                return

            html = render_report_html(report_type, scope, ctx)

            # PDF generation
            pdf_path = None
            pdf_filename = None
            if include_pdf:
                if scope == 'team':
                    identity = 'team'
                else:
                    agent_info = _get_agent_info(db, agent_id) if agent_id else {}
                    identity = agent_info.get('agent_name') or agent_info.get('hostname') or agent_info.get('username') or agent_id

                pdf_filename = build_report_filename(
                    report_type=report_type,
                    scope=scope,
                    identity=identity,
                    start_date=start_date,
                    end_date=end_date,
                    export_id=job_id[:8] if job_id else None,
                    ext='pdf',
                )
                target_pdf = get_reports_storage_dir() / pdf_filename
                ok, result = generate_pdf(html, target_pdf)
                if ok:
                    pdf_path = result
                else:
                    logger.warning(f"[REPORTS] PDF generation failed for job {job_id}: {result}")

            # Save job result
            from server_models import ReportGenerationJob
            job = db.session.get(ReportGenerationJob, job_id)
            if job:
                job.status = 'completed'
                job.result_html = html
                job.result_pdf_path = pdf_path
                job.completed_at = utcnow_naive()  # D02 / FR-009: naive UTC column
                meta_identity = 'team' if scope == 'team' else (_get_agent_info(db, agent_id).get('agent_name') if agent_id else agent_id)
                job_progress = dict(job.progress) if job.progress else {}
                job_progress['export_metadata'] = build_report_metadata(
                    report_type=report_type,
                    scope=scope,
                    identity=meta_identity or identity if 'identity' in locals() else 'unknown',
                    start_date=start_date,
                    end_date=end_date,
                    export_id=job_id[:8] if job_id else None,
                    ext='pdf',
                    file_path=pdf_path,
                )
                job.progress = job_progress
                db.session.commit()

            if auto_email and recipients:
                attachments = []
                if pdf_path and os.path.exists(pdf_path):
                    attachments.append({
                        'path': str(pdf_path),
                        'filename': os.path.basename(str(pdf_path)),
                        'content_type': 'application/pdf',
                    })
                else:
                    html_filename = build_report_filename(
                        report_type=report_type,
                        scope=scope,
                        identity=meta_identity or (identity if 'identity' in locals() else 'report'),
                        start_date=start_date,
                        end_date=end_date,
                        export_id=job_id[:8] if job_id else None,
                        ext='html',
                    )
                    target_html = get_reports_storage_dir() / html_filename
                    try:
                        safe_write_file(target_html, html)
                    except Exception:
                        with open(target_html, 'w', encoding='utf-8') as f:
                            f.write(html)
                    attachments.append({
                        'path': str(target_html),
                        'filename': html_filename,
                        'content_type': 'text/html',
                    })

                body_html = render_email_body_html(
                    report_type=report_type,
                    scope=scope,
                    start_date=start_date,
                    end_date=end_date,
                    attachments=attachments,
                )
                subject = f"SentinelEdge {report_type.title()} {scope.title()} Report — {start_date} to {end_date}"
                ok, err = send_report_email(
                    body_html, recipients, subject,
                    report_type=report_type, scope=scope,
                    start_date=start_date, end_date=end_date,
                    attachments=attachments,
                )
                if not ok:
                    logger.warning(f"[REPORTS] Job {job_id}: email failed — {err}")
                    job = db.session.get(ReportGenerationJob, job_id)
                    if job:
                        job.error_message = f"Report generated but email failed: {err}"
                        db.session.commit()

        except Exception as e:
            logger.exception(f"[REPORTS] Job {job_id} failed: {e}")
            fail_job(db, job_id, str(e))


# ── Multi-sheet inventory export (feature 037, D15 / FR-025b–h) ───────────────
#
# QA reported the combined app-inventory download as "agents app inventories are
# displaying again and again". The cause is presentation, not data: the combined
# export flattened every agent's inventory into one undivided list, so every
# application common to the fleet appeared once per agent with nothing marking
# where one agent ended and the next began. QA's own suggestion was one sheet per
# agent, which is what this produces.

#: Maximum agents in a single combined export.
#:
#: FR-025f/g. The export runs inside the request, and gunicorn kills a worker at
#: 120 seconds (gunicorn_config.py). Refusing an oversized request with a clear
#: message beats letting it run into a timeout the user cannot interpret.
#:
#: Derived by measurement (T119, recorded in investigation-findings.md). At 120
#: applications per agent, workbook generation is close to linear at roughly
#: 20 ms per agent: 750 agents 16.3 s, 1000 agents 18.9 s, 1500 agents 30.5 s.
#: 1000 agents therefore costs ~19 s of the 120 s budget, leaving the rest for
#: the database query and transfer, which are not included in that figure.
#:
#: Measured on a dev machine against synthetic data. Re-measure against the real
#: fleet before relying on the headroom. Background job infrastructure is
#: deliberately out of scope (FR-025h) — this cap is what keeps the synchronous
#: implementation honest.
MAX_COMBINED_EXPORT_AGENTS = 1000

#: Excel's own limits, not ours.
_SHEET_NAME_MAX = 31
_SHEET_NAME_ILLEGAL = set(r':\/?*[]')

_INVENTORY_HEADERS = ["Application", "Version", "Publisher", "Source", "Install Date"]


class InventoryExportTooLarge(Exception):
    """Raised when a combined export would exceed MAX_COMBINED_EXPORT_AGENTS."""


def safe_sheet_name(raw_name, used):
    r"""
    Derive a legal, unique worksheet name from an agent name.

    Excel caps names at 31 characters, forbids : \ / ? * [ ], and requires
    uniqueness within a workbook. Real agent names break all three — a
    domain-qualified name contains a backslash, and fleet naming conventions
    routinely produce names longer than 31 characters that share a prefix.

    FR-025c forbids the two failure modes that a naive implementation produces:
    silently colliding (two agents landing on one sheet, so one agent's data is
    invisible) and failing the export outright. Both are worse than a slightly
    ugly name, so this always returns something usable.

    `used` is the set of names already taken in this workbook; the caller adds
    the returned value to it.
    """
    name = ''.join(c for c in str(raw_name or '') if c not in _SHEET_NAME_ILLEGAL).strip()
    # Excel also rejects a leading or trailing apostrophe.
    name = name.strip("'")
    if not name:
        name = "Unnamed agent"

    candidate = name[:_SHEET_NAME_MAX]
    if candidate not in used:
        return candidate

    # Disambiguate with a numeric suffix, trimming the stem so the total still
    # fits. Distinct agents whose names share a long prefix land here.
    for n in range(2, 1000):
        suffix = f" ({n})"
        candidate = f"{name[:_SHEET_NAME_MAX - len(suffix)]}{suffix}"
        if candidate not in used:
            return candidate

    # Pathological fallback — cannot collide because `used` is finite.
    return f"Sheet {len(used) + 1}"[:_SHEET_NAME_MAX]


def _group_rows_by_agent(rows):
    """Group fleet-export rows by agent, preserving first-seen agent order."""
    grouped = {}
    for row in rows or []:
        agent_id = str(row.get('agent_id') or '')
        hostname = row.get('agent_hostname') or ''
        key = (agent_id, hostname)
        grouped.setdefault(key, []).append(row)
    return grouped


def build_inventory_workbook(rows):
    """
    Build a multi-sheet inventory workbook, one worksheet per agent.

    `rows` is the shape /dashboard/api/inventory/fleet-export returns:
    agent_id, agent_hostname, name, version, publisher, source, install_date.

    Raises InventoryExportTooLarge when the selection exceeds
    MAX_COMBINED_EXPORT_AGENTS (FR-025f).
    """
    from openpyxl import Workbook

    grouped = _group_rows_by_agent(rows)

    if len(grouped) > MAX_COMBINED_EXPORT_AGENTS:
        raise InventoryExportTooLarge(
            f"This export covers {len(grouped)} agents, above the limit of "
            f"{MAX_COMBINED_EXPORT_AGENTS} for a single combined download. "
            f"Narrow the selection and try again."
        )

    wb = Workbook()
    wb.remove(wb.active)  # drop the default sheet; we add one per agent

    used_titles = set()
    for (agent_id, hostname), agent_rows in grouped.items():
        title = safe_sheet_name(hostname or agent_id, used_titles)
        used_titles.add(title)
        ws = wb.create_sheet(title=title)

        # FR-025c: identifiable by sheet name AND inside the sheet, so a single
        # printed or copied sheet still says which machine it describes.
        ws.append([f"Application Inventory — {hostname or 'Unnamed agent'}"])
        ws.append([f"Agent ID: {agent_id}"])
        ws.append([])
        ws.append(list(_INVENTORY_HEADERS))

        # FR-025d: the de-duplication required by FR-018 applies to this format
        # equally, keyed the same way as ingestion (name + version + location).
        seen = set()
        for row in agent_rows:
            app_name = (row.get('name') or '').strip()
            if not app_name:
                continue
            key = (app_name.casefold(), (row.get('version') or '').strip())
            if key in seen:
                continue
            seen.add(key)
            ws.append([
                app_name,
                row.get('version') or '',
                row.get('publisher') or '',
                row.get('source') or '',
                row.get('install_date') or '',
            ])

        widths = [42, 18, 30, 18, 14]
        for idx, width in enumerate(widths, start=1):
            ws.column_dimensions[ws.cell(row=1, column=idx).column_letter].width = width
        ws.freeze_panes = "A5"

    if not wb.worksheets:
        # An empty selection is an empty-state document, not a failure.
        ws = wb.create_sheet(title="No data")
        ws.append(["No application inventory was recorded for this selection."])

    return wb
