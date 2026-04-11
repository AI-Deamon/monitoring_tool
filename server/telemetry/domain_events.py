"""
Telemetry: Domain Events (domain-active + domain-switch)
"""
import logging
import json
from datetime import datetime, timezone
from flask import request, jsonify, g
from sqlalchemy import text
from extensions import db
import server_models
from server_auth import require_auth

from telemetry.helpers import (
    short_agent_id, safe_int, safe_float, parse_agent_timestamp,
    pick_earliest_timestamp, update_telemetry_time, store_raw_event,
)
from telemetry.screentime import bp

logger = logging.getLogger(__name__)


@bp.route('/domain-active', methods=['POST'])
@require_auth
def telemetry_domain_active():
    """
    LIVE LAYER: Handle active domain telemetry (every 30s).

    Rule: Update agent_current_status with current domain info.
    Dashboard: Shows what domain/website each user is viewing NOW.
    """
    data = request.get_json() or {}
    agent_id = str(g.current_agent.agent_id) if g.current_agent else None

    if not agent_id:
        return jsonify({'error': 'Missing agent_id'}), 400

    domain = data.get('domain')
    if not domain:
        return jsonify({'status': 'success', 'note': 'no domain'}), 200

    short_id = short_agent_id(agent_id)
    duration = safe_int(data.get('duration_seconds', 0))
    logger.info(f"[{short_id}] domain-active: {domain} ({duration}s)")

    try:
        browser = data.get('browser')
        url = data.get('url')
        username = data.get('username')
        duration = safe_int(data.get('duration_seconds', 0))
        is_active = data.get('is_active', True)

        ts_str = data.get('timestamp', datetime.now(timezone.utc).isoformat())
        timestamp_naive = parse_agent_timestamp(ts_str, agent_id)

        session_start_str = data.get('session_start')
        if session_start_str:
            try:
                session_start_naive = parse_agent_timestamp(session_start_str, agent_id)
            except:
                session_start_naive = timestamp_naive
        else:
            session_start_naive = timestamp_naive

        status = server_models.AgentCurrentStatus.query.filter_by(agent_id=agent_id).first()
        if status:
            if status.current_domain != domain:
                status.domain_session_start = session_start_naive
            status.current_domain = domain
            status.current_browser = browser
            status.current_url = url
            status.domain_duration_seconds = duration
            status.last_seen = timestamp_naive
            if username:
                status.username = username
        else:
            status = server_models.AgentCurrentStatus(
                agent_id=agent_id, username=username, current_domain=domain,
                current_browser=browser, current_url=url,
                domain_session_start=session_start_naive,
                domain_duration_seconds=duration, last_seen=timestamp_naive
            )
            db.session.add(status)

        update_telemetry_time(agent_id, pick_earliest_timestamp(session_start_naive, timestamp_naive))
        db.session.commit()
        return jsonify({'status': 'success'}), 200

    except Exception as e:
        db.session.rollback()
        logger.error(f"[{short_id}] domain-active ERROR: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/domain-switch', methods=['POST'])
@require_auth
def telemetry_domain_switch():
    """
    Handle domain switch event (on navigation) with AUDIT.

    Uses stored procedure: process_domain_switch_event()
    - APPENDS to domain_sessions (Detailed History)
    - INCREMENTS domain_usage (Daily Aggregation)
    - Records to telemetry_events (Audit)
    """
    data = request.get_json() or {}
    agent_id = str(g.current_agent.agent_id) if g.current_agent else None

    if not agent_id:
        return jsonify({'error': 'Missing agent_id'}), 400

    short_id = short_agent_id(agent_id)
    domain = data.get('domain', 'unknown')
    total_seconds = safe_int(data.get('total_seconds', 0))
    browser = data.get('browser', '')
    logger.info(f"[{short_id}] domain-switch: {domain} ({total_seconds}s, {browser})")

    raw_event = store_raw_event(agent_id, 'domain-switch', data, processed=False)

    try:
        domain = data.get('domain', 'unknown')
        browser = data.get('browser', '')
        url = data.get('url')
        total_seconds = safe_float(data.get('total_seconds', 0))

        ts_str = data.get('timestamp', datetime.now(timezone.utc).isoformat())
        start_str = data.get('session_start', datetime.now(timezone.utc).isoformat())
        end_str = data.get('session_end', datetime.now(timezone.utc).isoformat())

        timestamp_naive = parse_agent_timestamp(ts_str, agent_id)
        start_naive = parse_agent_timestamp(start_str, agent_id)
        end_naive = parse_agent_timestamp(end_str, agent_id)

        username = g.current_agent.username if hasattr(g.current_agent, 'username') else None

        result = db.session.execute(text("""
            SELECT * FROM process_domain_switch_event(
                :agent_id, :username, :domain, :raw_title, :raw_url, :browser,
                :session_start, :session_end, :duration_seconds, :idempotency_key
            )
        """), {
            'agent_id': agent_id, 'username': username, 'domain': domain,
            'raw_title': None, 'raw_url': url, 'browser': browser,
            'session_start': start_naive, 'session_end': end_naive,
            'duration_seconds': int(total_seconds), 'idempotency_key': None
        })

        row = result.fetchone()

        if raw_event:
            raw_event.processed = True

        update_telemetry_time(str(agent_id), pick_earliest_timestamp(start_naive, end_naive, timestamp_naive))
        db.session.commit()

        if row:
            status = row[0]
            message = row[1] if len(row) > 1 else ''
            if status == 'success':
                return jsonify({'status': 'success'}), 200
            elif status == 'skipped':
                logger.info(f"[{short_id}] domain-switch skipped: {message}")
                return jsonify({'status': 'skipped', 'message': message}), 200
            else:
                return jsonify({'status': 'error', 'message': message}), 500
        else:
            return jsonify({'status': 'error', 'message': 'No response from procedure'}), 500

    except Exception as e:
        db.session.rollback()
        logger.error(f"[{short_id}] domain-switch ERROR: {e}")
        if raw_event:
            try:
                failed_raw = server_models.RawEvent(
                    agent_id=agent_id, event_type='domain-switch',
                    sequence=data.get('sequence'), payload=json.dumps(data),
                    received_at=datetime.now(timezone.utc), processed=False, error=str(e)
                )
                db.session.add(failed_raw)
                db.session.commit()
            except:
                pass
        return jsonify({'error': str(e)}), 500
