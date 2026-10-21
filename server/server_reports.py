"""
server_reports.py — Report generation & email scheduling blueprint
Routes:
  POST /dashboard/reports/generate        → generate + return HTML preview
  POST /dashboard/reports/email           → generate + send email now
  GET  /dashboard/reports/schedules       → list schedules (JSON)
  POST /dashboard/reports/schedules       → create schedule (admin)
  DELETE /dashboard/reports/schedules/<id> → delete schedule (admin)
  POST /dashboard/reports/schedules/<id>/run → run schedule now (admin)
"""
import json
import logging
from threading import Thread
from datetime import timedelta, date, datetime, timezone
from flask import Blueprint, request, jsonify, Response, session, g, current_app
from extensions import db
from sqlalchemy import text
from auth import login_required, admin_required

# IST timezone (UTC+5:30)
IST = timezone(timedelta(hours=5, minutes=30))

logger = logging.getLogger(__name__)

reports_bp = Blueprint('reports', __name__)


def _parse_date(s):
    return datetime.strptime(s, '%Y-%m-%d').date()


def _get_schedules():
    rows = db.session.execute(text("""
        SELECT id, name, report_type, scope, agent_id, recipients,
               frequency, day_of_week, day_of_month, send_hour,
               enabled, last_run, next_run, created_by, created_at
        FROM report_schedules ORDER BY created_at DESC
    """)).fetchall()
    cols = ['id','name','report_type','scope','agent_id','recipients',
            'frequency','day_of_week','day_of_month','send_hour',
            'enabled','last_run','next_run','created_by','created_at']
    result = []
    for row in rows:
        d = dict(zip(cols, row))
        d['recipients'] = json.loads(d['recipients']) if d['recipients'] else []
        nr = d.get('next_run')
        if nr:
            send_hr = nr.hour
            send_min = nr.minute
        else:
            send_hr = d.get('send_hour') if d.get('send_hour') is not None else 9
            send_min = 0
        d['send_time'] = f"{send_hr:02d}:{send_min:02d}"
        d['last_run'] = (d['last_run'].replace(tzinfo=IST) if d['last_run'].tzinfo is None else d['last_run']).isoformat() if d['last_run'] else None
        d['next_run'] = (d['next_run'].replace(tzinfo=IST) if d['next_run'].tzinfo is None else d['next_run']).isoformat() if d['next_run'] else None
        d['created_at'] = d['created_at'].isoformat() if d['created_at'] else None
        result.append(d)
    return result


def _calc_next_run(frequency, day_of_week=None, day_of_month=None, send_hour=9, send_minute=0):
    """Calculate next run datetime from now in IST."""
    now = datetime.now(IST)
    h = 9 if send_hour is None else int(send_hour)
    m = 0 if send_minute is None else int(send_minute)

    if frequency == 'daily':
        candidate = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate
    elif frequency == 'weekly':
        dow = day_of_week if day_of_week is not None else 0  # 0=Monday
        days_ahead = (dow - now.weekday()) % 7
        candidate = now.replace(hour=h, minute=m, second=0, microsecond=0) + timedelta(days=days_ahead)
        if candidate <= now:
            candidate += timedelta(days=7)
        return candidate
    elif frequency == 'monthly':
        dom = day_of_month or 1
        import calendar
        _, max_days = calendar.monthrange(now.year, now.month)
        actual_dom = min(dom, max_days)
        candidate = now.replace(day=actual_dom, hour=h, minute=m, second=0, microsecond=0)
        if candidate <= now:
            if now.month == 12:
                next_year = now.year + 1
                next_month = 1
            else:
                next_year = now.year
                next_month = now.month + 1
            _, max_next = calendar.monthrange(next_year, next_month)
            candidate = candidate.replace(year=next_year, month=next_month, day=min(dom, max_next))
        return candidate
    return now + timedelta(hours=1)


def _run_schedule(schedule_id):
    """Execute a schedule: generate report and send email."""
    import os
    from engines.report_naming import build_report_filename, get_reports_storage_dir, safe_write_file
    from engines.report_engine import (
        build_individual_report,
        build_team_report,
        render_report_html,
        send_report_email,
        render_email_body_html,
        _get_agent_info,
        generate_pdf,
    )

    row = db.session.execute(text(
        "SELECT * FROM report_schedules WHERE id = :id"
    ), {'id': schedule_id}).fetchone()
    if not row:
        return False, 'Schedule not found'

    s = dict(row._mapping)

    start_date, end_date = _get_date_range(s['report_type'], s['frequency'])
    recipients = json.loads(s['recipients']) if isinstance(s['recipients'], str) else s['recipients']

    try:
        if s['scope'] == 'team':
            ctx = build_team_report(db, start_date, end_date)
        else:
            ctx = build_individual_report(db, s['agent_id'], start_date, end_date)

        if not ctx:
            return False, 'No data for report'

        html = render_report_html(s['report_type'], s['scope'], ctx)
        subject = f"SentinelEdge {s['report_type'].title()} {s['scope'].title()} Report — {start_date} to {end_date}"
        ok, err = send_report_email(
            html, recipients, subject,
            report_type=s['report_type'], scope=s['scope'],
            start_date=start_date, end_date=end_date
        )
        attachments = []
        identity = 'team' if s['scope'] == 'team' else (_get_agent_info(db, s['agent_id']).get('agent_name') or s['agent_id'])

        # 1. Generate and attach PDF report
        pdf_name = build_report_filename(
            report_type=s['report_type'],
            scope=s['scope'],
            identity=identity,
            start_date=start_date,
            end_date=end_date,
            ext='pdf',
        )
        target_pdf = get_reports_storage_dir() / pdf_name
        ok_pdf, pdf_res = generate_pdf(html, target_pdf)
        if ok_pdf and os.path.exists(pdf_res):
            attachments.append({
                'path': str(pdf_res),
                'filename': pdf_name,
                'content_type': 'application/pdf',
            })

        # 2. Generate and attach HTML report
        html_name = build_report_filename(
            report_type=s['report_type'],
            scope=s['scope'],
            identity=identity,
            start_date=start_date,
            end_date=end_date,
            ext='html',
        )
        target_html = get_reports_storage_dir() / html_name
        safe_write_file(content=html, target_path=target_html)
        attachments.append({
            'path': str(target_html),
            'filename': html_name,
            'content_type': 'text/html',
        })

        # Email body matching standard notification format
        email_body = render_email_body_html(
            report_type=s['report_type'],
            scope=s['scope'],
            agent_name=identity if s['scope'] != 'team' else None,
            team_name='Team' if s['scope'] == 'team' else None,
            start_date=str(start_date),
            end_date=str(end_date),
            attachments=attachments,
        )

        ok, err = send_report_email(email_body, recipients, subject, attachments=attachments if attachments else None)

        send_min = s['next_run'].minute if s.get('next_run') else 0
        next_run = _calc_next_run(s['frequency'], s.get('day_of_week'), s.get('day_of_month'), s.get('send_hour', 9), send_min)
        db.session.execute(text("""
            UPDATE report_schedules SET last_run = :now, next_run = :next WHERE id = :id
        """), {'now': datetime.now(IST), 'next': next_run, 'id': schedule_id})
        db.session.commit()

        return ok, err
    except Exception as e:
        logger.exception(f"[REPORTS] Schedule {schedule_id} failed: {e}")
        return False, str(e)


def _get_date_range(report_type, frequency):
    """Get start/end dates for a report based on type and frequency in IST."""
    today = datetime.now(IST).date()
    if report_type == 'daily' or frequency == 'daily':
        d = today - timedelta(days=1)
        return d, d
    elif report_type == 'weekly' or frequency == 'weekly':
        # Last complete Mon-Sun week
        days_since_mon = today.weekday()
        last_mon = today - timedelta(days=days_since_mon + 7)
        return last_mon, last_mon + timedelta(days=6)
    elif report_type == 'monthly' or frequency == 'monthly':
        # Last complete month
        first_this = today.replace(day=1)
        last_month_end = first_this - timedelta(days=1)
        last_month_start = last_month_end.replace(day=1)
        return last_month_start, last_month_end
    # fallback: last 7 days
    return today - timedelta(days=7), today - timedelta(days=1)


# ── Routes ────────────────────────────────────────────────────────────────────

@reports_bp.route('/dashboard/reports/generate', methods=['POST'])
@login_required
def generate_report():
    """Generate report HTML and return it for preview in new tab."""
    from engines.report_engine import build_individual_report, build_team_report, render_report_html

    data = request.get_json(force=True)
    report_type = data.get('report_type', 'weekly')   # weekly/monthly/daily
    scope = data.get('scope', 'team')                  # team/individual
    agent_id = data.get('agent_id')
    start_str = data.get('start_date') or data.get('date')
    end_str = data.get('end_date') or (start_str if report_type == 'daily' else None)

    try:
        start = _parse_date(start_str) if start_str else _get_date_range(report_type, report_type)[0]
        end = _parse_date(end_str) if end_str else _get_date_range(report_type, report_type)[1]
    except ValueError:
        return jsonify({'error': 'Invalid date format, use YYYY-MM-DD'}), 400

    # Access control: this endpoint is only @login_required, so a non-admin
    # could otherwise pull a team report covering EVERY agent, or an
    # individual report for any agent_id they guessed.
    from auth import can_view_agent
    is_admin = getattr(g.current_user, 'role', None) == 'admin'

    try:
        if scope == 'team':
            if not is_admin:
                logger.warning(
                    "[REPORTS] Non-admin %s denied team report",
                    getattr(g.current_user, 'username', '?'),
                )
                return jsonify({
                    'error': 'Team reports require administrator access'
                }), 403
            ctx = build_team_report(db, start, end)
        else:
            if not agent_id:
                return jsonify({'error': 'agent_id required for individual report'}), 400
            if not can_view_agent(agent_id):
                logger.warning(
                    "[REPORTS] User %s denied report for agent %s",
                    getattr(g.current_user, 'username', '?'), agent_id,
                )
                return jsonify({'error': 'Access denied for this agent'}), 403
            ctx = build_individual_report(db, agent_id, start, end)

        if not ctx:
            return jsonify({'error': 'No data found for the selected period'}), 404

        html = render_report_html(report_type, scope, ctx)
        return Response(html, mimetype='text/html')
    except Exception as e:
        logger.exception(f"[REPORTS] Generate failed: {e}")
        return jsonify({'error': str(e)}), 500


@reports_bp.route('/dashboard/reports/email', methods=['POST'])
@login_required
@admin_required
def email_report():
    """Generate report and send email immediately."""
    from engines.report_engine import build_individual_report, build_team_report, render_report_html, send_report_email

    data = request.get_json(force=True)
    report_type = data.get('report_type', 'weekly')
    scope = data.get('scope', 'team')
    agent_id = data.get('agent_id')
    start_str = data.get('start_date') or data.get('date')
    end_str = data.get('end_date') or (start_str if report_type == 'daily' else None)
    recipients = data.get('recipients', [])

    if not recipients:
        return jsonify({'error': 'recipients required'}), 400

    try:
        start = _parse_date(start_str) if start_str else _get_date_range(report_type, report_type)[0]
        end = _parse_date(end_str) if end_str else _get_date_range(report_type, report_type)[1]
    except ValueError:
        return jsonify({'error': 'Invalid date format'}), 400

    try:
        if scope == 'team':
            ctx = build_team_report(db, start, end)
        else:
            if not agent_id:
                return jsonify({'error': 'agent_id required'}), 400
            ctx = build_individual_report(db, agent_id, start, end)

        if not ctx:
            return jsonify({'error': 'No data found'}), 404

        html = render_report_html(report_type, scope, ctx)
        subject = f"SentinelEdge {report_type.title()} {scope.title()} Report — {start} to {end}"
        ok, err = send_report_email(html, recipients, subject)

        if ok:
            return jsonify({'success': True, 'message': f'Report sent to {len(recipients)} recipient(s)'})
        return jsonify({'success': False, 'error': err}), 500
    except Exception as e:
        logger.exception(f"[REPORTS] Email send failed: {e}")
        return jsonify({'error': str(e)}), 500


@reports_bp.route('/dashboard/reports/schedules', methods=['GET'])
@login_required
@admin_required  # schedules carry recipient email lists; creation/deletion is already admin-only
def list_schedules():
    try:
        return jsonify(_get_schedules())
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@reports_bp.route('/dashboard/reports/schedules', methods=['POST'])
@login_required
@admin_required
def create_schedule():
    data = request.get_json(force=True)
    required = ['name', 'report_type', 'scope', 'frequency', 'recipients']
    for f in required:
        if not data.get(f):
            return jsonify({'error': f'{f} is required'}), 400

    recipients = data['recipients']
    if isinstance(recipients, list):
        recipients = json.dumps(recipients)

    frequency = data['frequency']
    day_of_week = data.get('day_of_week')
    day_of_month = data.get('day_of_month')

    send_time = data.get('send_time')
    if send_time and ':' in str(send_time):
        parts = str(send_time).split(':')
        send_hour = int(parts[0])
        send_minute = int(parts[1])
    else:
        send_hour = int(data.get('send_hour', 9))
        send_minute = int(data.get('send_minute', 0))

    next_run = _calc_next_run(frequency, day_of_week, day_of_month, send_hour, send_minute)

    db.session.execute(text("""
        INSERT INTO report_schedules
            (name, report_type, scope, agent_id, recipients, frequency,
             day_of_week, day_of_month, send_hour, enabled, next_run, created_by)
        VALUES
            (:name, :rt, :scope, :aid, :rcpt, :freq,
             :dow, :dom, :hour, true, :next_run, :created_by)
    """), {
        'name': data['name'],
        'rt': data['report_type'],
        'scope': data['scope'],
        'aid': data.get('agent_id'),
        'rcpt': recipients,
        'freq': frequency,
        'dow': day_of_week,
        'dom': day_of_month,
        'hour': send_hour,
        'next_run': next_run,
        'created_by': session.get('username', 'admin'),
    })
    db.session.commit()
    return jsonify({'success': True, 'next_run': next_run.isoformat()})


@reports_bp.route('/dashboard/reports/schedules/<int:schedule_id>', methods=['DELETE'])
@login_required
@admin_required
def delete_schedule(schedule_id):
    db.session.execute(text("DELETE FROM report_schedules WHERE id = :id"), {'id': schedule_id})
    db.session.commit()
    return jsonify({'success': True})


@reports_bp.route('/dashboard/reports/schedules/<int:schedule_id>/run', methods=['POST'])
@login_required
@admin_required
def run_schedule_now(schedule_id):
    ok, err = _run_schedule(schedule_id)
    if ok:
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': err}), 500



# ── Unified async endpoints ───────────────────────────────────────────────────

@reports_bp.route('/dashboard/reports/unified/generate', methods=['POST'])
@login_required
def unified_generate():
    from engines.report_engine import create_job, run_report_job
    data = request.get_json(force=True)
    report_type = data.get('report_type', 'weekly')
    scope = data.get('scope', 'team')
    agent_id = data.get('agent_id')
    auto_email = data.get('auto_email', False)
    recipients = data.get('recipients', [])

    start_val = data.get('start_date') or data.get('date')
    end_val = data.get('end_date') or (start_val if report_type == 'daily' else None)

    try:
        start = _parse_date(start_val) if start_val else _get_date_range(report_type, report_type)[0]
        end = _parse_date(end_val) if end_val else _get_date_range(report_type, report_type)[1]
    except (ValueError, KeyError):
        return jsonify({'error': 'Invalid or missing date'}), 400

    if scope == 'individual' and not agent_id:
        return jsonify({'error': 'agent_id required for individual report'}), 400

    # Same access control as /reports/generate: without it any logged-in user
    # could queue a team report over every agent, or one for an agent they
    # have no access to - and have it emailed to an address they choose.
    from auth import can_view_agent
    is_admin = getattr(g.current_user, 'role', None) == 'admin'
    if scope == 'team':
        if not is_admin:
            return jsonify({
                'error': 'Team reports require administrator access'
            }), 403
    elif not can_view_agent(agent_id):
        return jsonify({'error': 'Access denied for this agent'}), 403

    # Emailing a report to arbitrary recipients is an admin action.
    if auto_email and not is_admin:
        return jsonify({
            'error': 'Emailing reports requires administrator access'
        }), 403

    job_id = create_job(db, report_type, scope, agent_id, start, end, created_by=session.get('username'))

    from flask import current_app
    app = current_app._get_current_object()
    t = Thread(
        target=run_report_job,
        args=(app, db, job_id, report_type, scope, agent_id, start, end, auto_email, recipients),
        daemon=True,
    )
    t.start()
    return jsonify({'job_id': job_id, 'status': 'pending'})


@reports_bp.route('/dashboard/reports/unified/jobs/<job_id>', methods=['GET'])
@login_required
def get_job_status(job_id):
    from engines.report_engine import get_job
    from server_models import ReportGenerationJob

    job = get_job(db, job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404

    # The payload includes result_html - the whole rendered report. Without
    # an owner check any logged-in user could poll job ids and read reports
    # (including admin team reports) that were never theirs.
    if getattr(g.current_user, 'role', None) != 'admin':
        row = ReportGenerationJob.query.filter_by(id=job_id).first()
        owner = getattr(row, 'created_by', None)
        if owner != getattr(g.current_user, 'username', None):
            return jsonify({'error': 'Job not found'}), 404

    return jsonify(job)


@reports_bp.route('/dashboard/reports/unified/jobs', methods=['GET'])
@login_required
def list_jobs():
    from server_models import ReportGenerationJob
    query = ReportGenerationJob.query
    # Non-admins only see their own jobs.
    if getattr(g.current_user, 'role', None) != 'admin':
        query = query.filter(
            ReportGenerationJob.created_by == getattr(
                g.current_user, 'username', None)
        )
    jobs = query.order_by(ReportGenerationJob.created_at.desc()).limit(20).all()
    return jsonify([{
        'job_id': j.id,
        'report_type': j.report_type,
        'scope': j.scope,
        'status': j.status,
        'created_at': j.created_at.isoformat() if j.created_at else None,
        'completed_at': j.completed_at.isoformat() if j.completed_at else None,
    } for j in jobs])


@reports_bp.route('/dashboard/reports/agents', methods=['GET'])
@login_required
def list_report_agents():
    from engines.report_engine import _query
    from auth import get_user_filter

    # Non-admins must not receive the full agent/username roster: scope the
    # list to the agents they are linked to (get_user_filter fails closed).
    user_filter = get_user_filter()
    if user_filter:
        agents = _query(db, """
            SELECT a.agent_id::text, a.hostname, acs.username
            FROM agents a
            JOIN agent_current_status acs ON a.agent_id = acs.agent_id
            WHERE a.status = 'active' AND acs.username IS NOT NULL
              AND (acs.username = :u OR acs.username ILIKE :suffix)
            ORDER BY acs.username
        """, {'u': user_filter, 'suffix': f'%\\{user_filter}'})
    else:
        agents = _query(db, """
            SELECT a.agent_id::text, a.hostname, acs.username
            FROM agents a
            JOIN agent_current_status acs ON a.agent_id = acs.agent_id
            WHERE a.status = 'active' AND acs.username IS NOT NULL
            ORDER BY acs.username
        """, {})
    return jsonify(agents)


@reports_bp.route('/dashboard/reports/unified/schedules', methods=['POST'])
@login_required
@admin_required
def create_unified_schedule():
    """Create a new report schedule with unified parameters (include_pdf, auto_email, recipients_json)."""
    data = request.get_json(force=True)
    required = ['name', 'report_type', 'scope', 'frequency', 'recipients']
    for f in required:
        if not data.get(f):
            return jsonify({'error': f'{f} is required'}), 400

    recipients = data['recipients']
    if isinstance(recipients, list):
        recipients_str = json.dumps(recipients)
    else:
        recipients_str = recipients

    frequency = data['frequency']
    day_of_week = data.get('day_of_week')
    day_of_month = data.get('day_of_month')

    send_time = data.get('send_time')
    if send_time and ':' in str(send_time):
        parts = str(send_time).split(':')
        send_hour = int(parts[0])
        send_minute = int(parts[1])
    else:
        send_hour = int(data.get('send_hour', 9))
        send_minute = int(data.get('send_minute', 0))

    next_run = _calc_next_run(frequency, day_of_week, day_of_month, send_hour, send_minute)

    db.session.execute(text("""
        INSERT INTO report_schedules
            (name, report_type, scope, agent_id, recipients, frequency,
             day_of_week, day_of_month, send_hour, enabled, next_run, created_by,
             include_pdf, auto_email, template_name, recipients_json)
        VALUES
            (:name, :rt, :scope, :aid, :rcpt, :freq,
             :dow, :dom, :hour, true, :next_run, :created_by,
             :include_pdf, :auto_email, :template_name, :recipients_json)
    """), {
        'name': data['name'],
        'rt': data['report_type'],
        'scope': data['scope'],
        'aid': data.get('agent_id'),
        'rcpt': recipients_str,
        'freq': frequency,
        'dow': day_of_week,
        'dom': day_of_month,
        'hour': send_hour,
        'next_run': next_run,
        'created_by': session.get('username', 'admin'),
        'include_pdf': bool(data.get('include_pdf', False)),
        'auto_email': bool(data.get('auto_email', True)),
        'template_name': data.get('template_name'),
        'recipients_json': json.dumps(recipients) if isinstance(recipients, list) else None,
    })
    db.session.commit()
    return jsonify({'success': True, 'next_run': next_run.isoformat()})


def _async_send_job_email(app, job_id, recipients, subject):
    with app.app_context():
        from engines.report_engine import get_job, send_report_email
        job = get_job(db, job_id)
        if not job or not job.get('result_html'):
            logger.error(f"[REPORTS] Background email dispatch failed: job {job_id} not found or missing HTML")
            return

        start_str = job.get('start_date') or ''
        end_str = job.get('end_date') or ''
        report_type = job.get('report_type') or 'weekly'
        scope = job.get('scope') or 'team'

        if not subject or subject == 'SentinelEdge Report':
            subject = f"Weekly Team Activity Report - {start_str} to {end_str}" if (start_str and end_str) else f"SentinelEdge {report_type.title()} {scope.title()} Report"

        ok, err = send_report_email(
            html_content=job['result_html'],
            recipients=recipients,
            subject=subject,
            report_type=report_type,
            scope=scope,
            start_date=start_str,
            end_date=end_str,
            pdf_path=job.get('result_pdf_path')
        )
        if not ok:
            logger.error(f"[REPORTS] Background email send for job {job_id} failed: {err}")


@reports_bp.route('/dashboard/reports/unified/jobs/<job_id>/email', methods=['POST'])
@login_required
@admin_required
def email_job_result(job_id):
    """Send report HTML and PDF as attachments with plain text and HTML body from a completed job in background thread."""
    from engines.report_engine import get_job
    import threading

    data = request.get_json(force=True)
    recipients = data.get('recipients', [])
    if not recipients:
        return jsonify({'error': 'recipients required'}), 400
    job = get_job(db, job_id)
    if not job or not job.get('result_html'):
        return jsonify({'error': 'Job not found or report not ready'}), 404

    subject = data.get('subject')
    app = current_app._get_current_object()
    thread = threading.Thread(
        target=_async_send_job_email,
        args=(app, job_id, recipients, subject),
        daemon=True
    )
    thread.start()

    return jsonify({'success': True, 'message': 'Email dispatch started in background'})
