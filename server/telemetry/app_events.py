"""
Telemetry: App Events (app-active + app-switch)
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
    VERBOSE_TELEMETRY,
)
from telemetry.screentime import bp

logger = logging.getLogger(__name__)


@bp.route('/app-active', methods=['POST'])
@require_auth
def telemetry_app_active():
    """
    Handle active app telemetry with backward compatible state detection.

    Supports:
    - New agents: Use explicit 'system_state' field from production state detector
    - Old agents: Infer state from 'state' field and app name (lock app detection)
    """
    data = request.get_json() or {}
    agent_id = str(g.current_agent.agent_id) if g.current_agent else None

    if not agent_id:
        return jsonify({'error': 'Missing agent_id'}), 400

    app = data.get('app')
    short_id = short_agent_id(agent_id)
    duration = safe_int(data.get('duration_seconds', 0))
    if duration >= 1 or VERBOSE_TELEMETRY:
        logger.info(f"[{short_id}] app-active: {app} ({duration}s)")

    try:
        window_title = data.get('window_title')
        username = data.get('username')
        duration = safe_int(data.get('duration_seconds', 0))

        # BACKWARD COMPATIBLE STATE DETECTION
        system_state = data.get('system_state')
        if system_state:
            current_state = system_state
            logger.debug(f"[STATE] Using explicit system_state: {current_state}")
        else:
            old_state = data.get('state', 'active')
            LOCK_APPS = ['lockapp.exe', 'logonui.exe', 'lockapp.exe', 'winlogon.exe']
            if app and app.lower() in [a.lower() for a in LOCK_APPS]:
                current_state = 'locked'
                logger.debug(f"[STATE] Detected lock from app name: {app}")
            elif old_state == 'idle':
                current_state = 'idle'
            else:
                current_state = 'active'

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
            if status.current_app != app:
                status.session_start = session_start_naive
            status.current_app = app
            status.window_title = window_title
            status.duration_seconds = duration
            status.current_state = current_state
            status.last_seen = timestamp_naive
            if username:
                status.username = username
        else:
            status = server_models.AgentCurrentStatus(
                agent_id=agent_id, username=username, current_app=app,
                window_title=window_title, current_state=current_state,
                session_start=session_start_naive, duration_seconds=duration,
                last_seen=timestamp_naive
            )
            db.session.add(status)

        update_telemetry_time(agent_id, pick_earliest_timestamp(session_start_naive, timestamp_naive))
        db.session.commit()
        return jsonify({'status': 'success'}), 200

    except Exception as e:
        db.session.rollback()
        logger.error(f"[{short_id}] app-active ERROR: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@bp.route('/app-switch', methods=['POST'])
@require_auth
def telemetry_app_switch():
    """
    HISTORICAL LAYER: Handle app switch event (on app change) with AUDIT.

    Uses stored procedure: process_app_switch_event()
    - APPENDS to app_sessions (Detailed History)
    - INCREMENTS app_usage (Daily Aggregation)
    - Records to telemetry_events (Audit)

    total_seconds = FINAL duration of completed session (SOURCE OF TRUTH)
    """
    data = request.get_json() or {}
    agent_id = str(g.current_agent.agent_id) if g.current_agent else None

    if not agent_id:
        return jsonify({'error': 'Missing agent_id'}), 400

    short_id = short_agent_id(agent_id)
    app = data.get('app', 'unknown')
    total_seconds = safe_int(data.get('total_seconds', 0))
    category = data.get('category', 'other')
    logger.info(f"[{short_id}] app-switch: {app} ({total_seconds}s, {category})")
    if VERBOSE_TELEMETRY:
        logger.debug(f"[{short_id}] app-switch FULL: {data}")

    raw_event = store_raw_event(agent_id, 'app-switch', data, processed=False)

    try:
        app = data.get('app', 'unknown')
        friendly_name = data.get('friendly_name', app)
        category = data.get('category', 'other')
        window_title = data.get('window_title', '')
        total_seconds = safe_float(data.get('total_seconds', 0))

        ts_str = data.get('timestamp', datetime.now(timezone.utc).isoformat())
        start_str = data.get('session_start', datetime.now(timezone.utc).isoformat())
        end_str = data.get('session_end', datetime.now(timezone.utc).isoformat())

        timestamp_naive = parse_agent_timestamp(ts_str, agent_id)
        start_naive = parse_agent_timestamp(start_str, agent_id)
        end_naive = parse_agent_timestamp(end_str, agent_id)

        result = db.session.execute(text("""
            SELECT * FROM process_app_switch_event(
                :agent_id, :timestamp, :app, :friendly_name, :category,
                :window_title, :session_start, :session_end, :total_seconds
            )
        """), {
            'agent_id': agent_id, 'timestamp': timestamp_naive, 'app': app,
            'friendly_name': friendly_name, 'category': category,
            'window_title': window_title, 'session_start': start_naive,
            'session_end': end_naive, 'total_seconds': total_seconds
        })

        row = result.fetchone()

        if raw_event:
            raw_event.processed = True

        update_telemetry_time(agent_id, pick_earliest_timestamp(start_naive, end_naive, timestamp_naive))
        db.session.commit()

        if row:
            status = row[0]
            message = row[1] if len(row) > 1 else ''
            if status == 'success':
                return jsonify({'status': 'success'}), 200
            elif status == 'skipped':
                logger.info(f"[{short_id}] app-switch skipped: {message}")
                return jsonify({'status': 'skipped', 'message': message}), 200
            else:
                return jsonify({'status': 'error', 'message': message}), 500
        else:
            return jsonify({'status': 'error', 'message': 'No response from procedure'}), 500

    except Exception as e:
        db.session.rollback()
        logger.error(f"[{short_id}] app-switch ERROR: {e}")
        if raw_event:
            try:
                failed_raw = server_models.RawEvent(
                    agent_id=agent_id, event_type='app-switch',
                    sequence=data.get('sequence'), payload=json.dumps(data),
                    received_at=datetime.now(timezone.utc), processed=False, error=str(e)
                )
                db.session.add(failed_raw)
                db.session.commit()
            except:
                pass
        return jsonify({'error': str(e)}), 500
