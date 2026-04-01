"""
Telemetry: State Spans (state-change, event, state_duration, screentime-spans, root endpoints)
"""
import logging
import json
from datetime import datetime, timezone
from typing import Optional
from flask import request, jsonify, g
from sqlalchemy import text
from extensions import db
import server_models
from server_auth import require_auth

from telemetry.helpers import (
    short_agent_id, safe_int, safe_float, parse_agent_timestamp, parse_agent_time,
    pick_earliest_timestamp, update_telemetry_time, store_raw_event, validate_span,
)
from telemetry.screentime import bp

logger = logging.getLogger(__name__)


@bp.route('/state-change', methods=['POST'])
@require_auth
def telemetry_state_change():
    """Handle state change event (active/idle/locked) with duration tracking and AWAY classification."""
    data = request.get_json() or {}
    agent_id = g.current_agent.agent_id if g.current_agent else None

    if not agent_id:
        return jsonify({'error': 'Missing agent_id'}), 400

    short_id = short_agent_id(agent_id)
    previous_state = data.get('previous_state', 'unknown')
    current_state = data.get('current_state', 'unknown')
    duration = safe_float(data.get('duration_seconds', 0))
    logger.info(f"[{short_id}] state-change: {previous_state}→{current_state} (Δ{int(duration)}s)")

    raw_event = store_raw_event(agent_id, 'state-change', data, processed=False)

    try:
        ts_str = data.get('timestamp', datetime.utcnow().isoformat())
        ts_naive = parse_agent_timestamp(ts_str, agent_id)

        previous_state = data.get('previous_state', 'unknown')
        current_state = data.get('current_state', 'unknown')

        state_change = server_models.StateChange(
            agent_id=agent_id, username=data.get('username'),
            previous_state=previous_state, current_state=current_state,
            timestamp=ts_naive
        )
        db.session.add(state_change)

        # DONE: Agent now handles Away classification. 
        # Server simply stores what it receives.

        if raw_event:
            raw_event.processed = True

        update_telemetry_time(agent_id, ts_naive)
        db.session.commit()
        return jsonify({'status': 'success'}), 200

    except Exception as e:
        db.session.rollback()
        logger.error(f"[{short_id}] state-change ERROR: {e}")
        if raw_event:
            try:
                failed_raw = server_models.RawEvent(
                    agent_id=agent_id, event_type='state-change',
                    sequence=data.get('sequence'), payload=json.dumps(data),
                    received_at=datetime.utcnow(), processed=False, error=str(e)
                )
                db.session.add(failed_raw)
                db.session.commit()
            except:
                pass
        return jsonify({'error': str(e)}), 500


@bp.route('/event', methods=['POST'])
@require_auth
def telemetry_event():
    """Generic telemetry event receiver. Routes events by type."""
    data = request.get_json() or {}
    agent_id = g.current_agent.agent_id if g.current_agent else None

    if not agent_id:
        return jsonify({'error': 'Missing agent_id'}), 400

    event_type = data.get('type') or data.get('event')
    short_id = short_agent_id(agent_id)

    if event_type == 'state_duration_event' or event_type == 'state_duration':
        return process_state_duration_event(data)

    logger.info(f"[{short_id}] Received unknown event type: {event_type}")
    return jsonify({'status': 'ignored', 'message': f'Unknown event type: {event_type}'}), 200


def process_state_duration_event(payload: dict):
    """
    AUTHORITATIVE Event Handler (Step 367).
    Processes state_duration events as the SINGLE SOURCE OF TRUTH.
    """
    agent_id = payload["agent_id"]
    short_id = short_agent_id(agent_id)
    state = payload.get("state")
    duration = safe_float(payload.get("duration_seconds", 0))
    ts_str = payload.get("timestamp")

    if not state or duration <= 0:
        logger.info(f"[{short_id}] Dropping invalid event: {state} {duration}s")
        return jsonify({'status': 'ignored'}), 200

    # Away-time classification (Step 367 rule: locked > 7200s -> away_seconds)
    delta_active = delta_idle = delta_locked = delta_away = 0
    # Agent is the source of truth for state classification.
    if state == "active":
        delta_active = duration
    elif state == "idle":
        delta_idle = duration
    elif state == "locked":
        delta_locked = duration
    elif state == "away":
        delta_away = duration

    try:
        timestamp = parse_agent_time(ts_str)
        db.session.execute(
            text("""
                SELECT * FROM process_screentime_delta(
                    :agent_id, :timestamp, :active, :idle, :locked, :state, :away
                )
            """),
            {
                "agent_id": agent_id, "timestamp": timestamp,
                "active": int(delta_active), "idle": int(delta_idle),
                "locked": int(delta_locked), "state": state,
                "away": int(delta_away),
            }
        )
        db.session.commit()
        logger.info(f"[{short_id}] Processed state_duration: {state} +{duration:.1f}s (IST: {timestamp.strftime('%H:%M')})")
        return jsonify({'status': 'success'}), 200

    except Exception as e:
        db.session.rollback()
        logger.error(f"[{short_id}] process_state_duration ERROR: {e}")
        return jsonify({'error': str(e)}), 500


@bp.route('/screentime-spans', methods=['POST'])
@require_auth
def telemetry_screentime_spans():
    """
    Process batches of idempotent screen time spans.
    Uses ON CONFLICT (span_id) DO NOTHING to prevent duplicates.
    """
    data = request.get_json() or {}
    agent_id = str(g.current_agent.agent_id) if g.current_agent else None

    if not agent_id:
        return jsonify({'error': 'Missing agent_id'}), 400

    spans = data.get('spans', [])
    if not spans:
        return jsonify({'status': 'success', 'count': 0}), 200

    short_id = short_agent_id(agent_id)
    logger.info(f"[{short_id}] Received {len(spans)} screen time spans")

    store_raw_event(agent_id, 'screentime-spans', data)

    stored_count = 0
    batch_earliest: Optional[datetime] = None
    errors = []

    try:
        for span in spans:
            val_error = validate_span(span, agent_id)
            if val_error:
                logger.warning(f"[{short_id}] Invalid span {span.get('span_id')}: {val_error}")
                errors.append({"span_id": span.get('span_id'), "error": val_error})
                continue

            start = parse_agent_timestamp(span['start_time'], agent_id)
            end = parse_agent_timestamp(span['end_time'], agent_id)
            batch_earliest = pick_earliest_timestamp(batch_earliest, start, end)

            db.session.execute(text("""
                INSERT INTO screen_time_spans (
                    span_id, agent_id, state, start_time, end_time, duration_seconds
                ) VALUES (
                    :span_id, :agent_id, :state, :start, :end, :duration
                ) ON CONFLICT (span_id) DO NOTHING
            """), {
                'span_id': span['span_id'], 'agent_id': agent_id,
                'state': span['state'], 'start': start, 'end': end,
                'duration': int(span['duration_seconds'])
            })
            stored_count += 1

        update_telemetry_time(agent_id, batch_earliest)
        db.session.commit()

        return jsonify({
            'status': 'success', 'count': stored_count,
            'errors': errors if errors else None
        }), 200

    except Exception as e:
        db.session.rollback()
        logger.error(f"[{short_id}] screentime-spans ERROR: {e}")
        return jsonify({'error': str(e)}), 500


def register_root_telemetry_endpoints(app):
    """Register telemetry endpoints at root level for agent compatibility."""
    from telemetry.screentime import telemetry_screentime
    from telemetry.app_events import telemetry_app_active, telemetry_app_switch
    from telemetry.domain_events import telemetry_domain_active, telemetry_domain_switch

    @app.route('/telemetry/screentime', methods=['POST'])
    @require_auth
    def root_telemetry_screentime():
        return telemetry_screentime()

    @app.route('/telemetry/app-active', methods=['POST'])
    @require_auth
    def root_telemetry_app_active():
        return telemetry_app_active()

    @app.route('/telemetry/domain-active', methods=['POST'])
    @require_auth
    def root_telemetry_domain_active():
        return telemetry_domain_active()

    @app.route('/telemetry/app-switch', methods=['POST'])
    @require_auth
    def root_telemetry_app_switch():
        return telemetry_app_switch()

    @app.route('/telemetry/domain-switch', methods=['POST'])
    @require_auth
    def root_telemetry_domain_switch():
        return telemetry_domain_switch()

    @app.route('/telemetry/state-change', methods=['POST'])
    @require_auth
    def root_telemetry_state_change():
        return telemetry_state_change()

    @app.route('/telemetry/screentime-spans', methods=['POST'])
    @require_auth
    def root_telemetry_screentime_spans():
        return telemetry_screentime_spans()
