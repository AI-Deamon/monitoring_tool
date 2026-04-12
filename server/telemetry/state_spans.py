"""
Telemetry: State Spans (state-change, event, state_duration, screentime-spans, root endpoints)
"""
import logging
import json
from datetime import datetime, timezone, timedelta
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
        ts_str = data.get('timestamp', datetime.now(timezone.utc).isoformat())
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
                    received_at=datetime.now(timezone.utc), processed=False, error=str(e)
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
        payload = dict(data or {})
        payload["agent_id"] = str(agent_id)
        return process_state_duration_event(payload)

    logger.info(f"[{short_id}] Received unknown event type: {event_type}")
    return jsonify({'status': 'ignored', 'message': f'Unknown event type: {event_type}'}), 200


def process_state_duration_event(payload: dict):
    """
    AUTHORITATIVE Event Handler (Step 367).
    Processes state_duration events as the SINGLE SOURCE OF TRUTH.
    
    ✅ OFFLINE-FIRST: Handles spans that cross midnight by splitting them.
    This ensures accurate daily totals even when agents are offline for days.
    """
    agent_id = payload.get("agent_id")
    if not agent_id:
        return jsonify({'error': 'Missing agent_id'}), 400
    short_id = short_agent_id(agent_id)
    state = payload.get("state")
    duration = safe_float(payload.get("duration_seconds", 0))
    ts_str = payload.get("timestamp")

    if not state or duration <= 0:
        logger.info(f"[{short_id}] Dropping invalid event: {state} {duration}s")
        return jsonify({'status': 'ignored'}), 200

    # ✅ OFFLINE-FIRST: Check if this is a span with explicit start/end times
    # that may cross midnight boundary
    start_time_str = payload.get("start_time")
    end_time_str = payload.get("end_time")
    
    if start_time_str and end_time_str:
        try:
            start_time = parse_agent_time(start_time_str)
            end_time = parse_agent_time(end_time_str)
            
            # Detect if span crosses midnight
            if end_time.date() > start_time.date():
                logger.info(
                    f"[{short_id}] Detected midnight-crossing span: "
                    f"{state} {start_time.strftime('%H:%M')} → {end_time.strftime('%H:%M')} "
                    f"({duration:.0f}s)"
                )
                return _process_split_span(
                    agent_id, short_id, state,
                    start_time, end_time, duration
                )
        except Exception as e:
            logger.warning(f"[{short_id}] Failed to parse span times: {e}")
            # Fall through to normal processing if parsing fails
    
    # Normal case: span within single day (or legacy format without explicit times)
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
    else:
        logger.info(f"[{short_id}] Dropping unknown state_duration state: {state}")
        return jsonify({'status': 'ignored', 'reason': 'unknown_state'}), 200

    try:
        timestamp = parse_agent_time(ts_str) if ts_str else datetime.now(timezone.utc)
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


def _process_split_span(agent_id: str, short_id: str, state: str,
                        start_time: datetime, end_time: datetime,
                        total_duration: float):
    """
    Split a span that crosses midnight into two separate daily spans.
    
    Example:
        Input: 7 PM (Day 1) → 10 AM (Day 2) = 15 hours Away
        Output:
            Day 1: 7 PM - 12 AM = 5 hours Away
            Day 2: 12 AM - 10 AM = 10 hours Away
    
    This is critical for offline-first agents that buffer spans while
    disconnected from the server.
    
    Returns:
        Flask response with split results
    """
    try:
        # Calculate midnight between start and end (in span's timezone)
        midnight = datetime(
            start_time.year, start_time.month, start_time.day,
            tzinfo=start_time.tzinfo
        ) + timedelta(days=1)
        
        # Calculate durations for each day
        day1_duration = (midnight - start_time).total_seconds()
        day2_duration = (end_time - midnight).total_seconds()
        
        # Sanity check: ensure split durations sum to total
        assert abs((day1_duration + day2_duration) - total_duration) < 1.0, \
            f"Split duration mismatch: {day1_duration} + {day2_duration} != {total_duration}"
        
        logger.info(
            f"[{short_id}] Splitting midnight-crossing span: "
            f"{state} {total_duration:.0f}s → "
            f"Day1: {day1_duration:.0f}s ({start_time.strftime('%H:%M')}-{midnight.strftime('%H:%M')}), "
            f"Day2: {day2_duration:.0f}s ({midnight.strftime('%H:%M')}-{end_time.strftime('%H:%M')})"
        )
        
        # Classify state for Day 1
        day1_active = day1_idle = day1_locked = day1_away = 0
        if state == "active":
            day1_active = day1_duration
        elif state == "idle":
            day1_idle = day1_duration
        elif state == "locked":
            day1_locked = day1_duration
        elif state == "away":
            day1_away = day1_duration
        
        # Classify state for Day 2
        day2_active = day2_idle = day2_locked = day2_away = 0
        if state == "active":
            day2_active = day2_duration
        elif state == "idle":
            day2_idle = day2_duration
        elif state == "locked":
            day2_locked = day2_duration
        elif state == "away":
            day2_away = day2_duration
        
        # Insert Day 1 span
        db.session.execute(
            text("""
                SELECT * FROM process_screentime_delta(
                    :agent_id, :timestamp, :active, :idle, :locked, :state, :away
                )
            """),
            {
                "agent_id": agent_id,
                "timestamp": start_time,
                "active": int(day1_active),
                "idle": int(day1_idle),
                "locked": int(day1_locked),
                "state": state,
                "away": int(day1_away),
            }
        )
        
        # Insert Day 2 span
        db.session.execute(
            text("""
                SELECT * FROM process_screentime_delta(
                    :agent_id, :timestamp, :active, :idle, :locked, :state, :away
                )
            """),
            {
                "agent_id": agent_id,
                "timestamp": midnight,
                "active": int(day2_active),
                "idle": int(day2_idle),
                "locked": int(day2_locked),
                "state": state,
                "away": int(day2_away),
            }
        )
        
        db.session.commit()
        
        logger.info(
            f"[{short_id}] Successfully split and processed midnight-crossing span: "
            f"{state} ({day1_duration/3600:.1f}h + {day2_duration/3600:.1f}h)"
        )
        
        return jsonify({
            'status': 'success',
            'split': True,
            'day1_seconds': int(day1_duration),
            'day2_seconds': int(day2_duration),
            'day1_date': start_time.date().isoformat(),
            'day2_date': midnight.date().isoformat()
        }), 200
    
    except Exception as e:
        db.session.rollback()
        logger.error(f"[{short_id}] Failed to split midnight-crossing span: {e}", exc_info=True)
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
    duplicate_count = 0
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

            insert_result = db.session.execute(text("""
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
            if insert_result.rowcount and insert_result.rowcount > 0:
                stored_count += 1
            else:
                duplicate_count += 1

        update_telemetry_time(agent_id, batch_earliest)
        db.session.commit()

        failed_count = len(errors)
        return jsonify({
            'status': 'success',
            'count': stored_count,
            'stored': stored_count,
            'duplicates': duplicate_count,
            'rejected': failed_count,
            'total': len(spans),
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
