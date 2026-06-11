"""
SentinelEdge Server - Telemetry Endpoints

Handles all telemetry data uploads:
- /api/v1/telemetry/screentime
- /api/v1/telemetry/app-active
- /api/v1/telemetry/domain-active
- /api/v1/telemetry/app-switch
- /api/v1/telemetry/domain-switch
- /api/v1/telemetry/state-change

All endpoints require X-API-Key authentication.
"""

import logging
import json
import math
from datetime import datetime, date, timezone, timedelta
from typing import Optional
from flask import Blueprint, request, jsonify, g
from sqlalchemy import text
from extensions import db
import server_models
from server_auth import require_auth

# Import Pydantic schemas for validation
from pydantic import ValidationError
from schemas import (
    ScreentimeSchema,
    AppActiveSchema,
    AppSwitchSchema,
    DomainActiveSchema,
    DomainSwitchSchema,
    StateChangeSchema
)

# Try to import pytz for timezone handling
try:
    import pytz
    _PYTZ_AVAILABLE = True
except ImportError:
    _PYTZ_AVAILABLE = False

logger = logging.getLogger(__name__)
bp = Blueprint('telemetry', __name__)

RECOVERY_ACTIVE_SPAN_CAP_SECONDS = 8 * 3600

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

# Server timezone (matches PostgreSQL stored procedures)
SERVER_TIMEZONE = 'Asia/Kolkata'

def get_server_tz():
    """Get server timezone object."""
    if _PYTZ_AVAILABLE:
        return pytz.timezone(SERVER_TIMEZONE)
    else:
        # Fallback: IST is UTC+5:30
        return timezone(timedelta(hours=5, minutes=30))


def pick_earliest_timestamp(*values: Optional[datetime]) -> Optional[datetime]:
    """Return earliest non-null timestamp."""
    candidates = [v for v in values if isinstance(v, datetime)]
    if not candidates:
        return None
    return min(candidates)


def update_telemetry_time(agent_id: str, event_timestamp: Optional[datetime] = None):
    """
    Update last_telemetry_time for an agent when actual telemetry data is received.
    This is different from last_seen which is updated on any authenticated request.
    
    Used to detect "silent failures" - agents that are online but not sending data.
    """
    try:
        agent = server_models.Agent.query.filter_by(agent_id=agent_id).first()
        if agent:
            # Keep liveness heartbeat based on receive time (not event time).
            agent.last_telemetry_time = datetime.now(get_server_tz())

            # Canonical first activity must come from telemetry event timestamp.
            if event_timestamp is not None:
                if not agent.first_activity_at or event_timestamp < agent.first_activity_at:
                    agent.first_activity_at = event_timestamp
            # Don't commit here - let the calling function handle the commit
    except Exception as e:
        logger.warning(f"Failed to update telemetry time for {short_agent_id(agent_id)}: {e}")


def parse_agent_timestamp(ts_str: str, agent_id: str = None) -> datetime:
    """
    Parse and normalize agent timestamps with robust timezone handling
    
    - New agents (v1.2+): Send IST timestamp with +05:30
    - Old agents (v1.0-1.1): Send UTC timestamp with Z
    
    Enhanced validation with better error handling and DST support.
    
    Returns: Naive datetime in server timezone (IST)
    """
    short_id = short_agent_id(agent_id) if agent_id else "??????"
    
    try:
        # Validate input format
        if not ts_str or not isinstance(ts_str, str) or not ts_str.strip():
            raise ValueError("Invalid timestamp format")
            
        # Parse ISO format with timezone validation
        ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
        
        # Validate timezone information
        if ts.tzinfo is None:
            logger.warning(f"[{short_id}] Legacy timestamp without timezone: {ts_str}")
            ts = ts.replace(tzinfo=timezone.utc)
            
        # Validate timestamp range (enhanced from original)
        now = datetime.now(get_server_tz())
        max_future = now + timedelta(hours=2)  # Reduce clock drift tolerance
        min_past = now - timedelta(days=365)
        
        if ts > max_future:
            logger.warning(f"[{short_id}] Timestamp too far in future: {ts_str}")
            return now.astimezone(get_server_tz()).replace(tzinfo=None)
        if ts < min_past:
            logger.warning(f"[{short_id}] Timestamp too old: {ts_str}")
            raise ValueError("Timestamp outside valid range")
            
        # Convert to server timezone with proper DST support
        server_tz = get_server_tz()
        ts_local = ts.astimezone(server_tz)
        
        # Return naive datetime in server timezone (for PostgreSQL)
        return ts_local.replace(tzinfo=None)
        
    except Exception as e:
        logger.error(f"[{short_id}] Failed to parse timestamp: {ts_str} - {e}")
        # Fallback: use current server time
        if _PYTZ_AVAILABLE:
            return datetime.now(pytz.timezone(SERVER_TIMEZONE)).replace(tzinfo=None)
        else:
            return datetime.now(get_server_tz()).replace(tzinfo=None)


def safe_int(value, default=0, min_val=0, max_val=86400) -> int:
    """
    Safely convert value to integer with validation.
    
    Prevents:
    - NaN, Infinity from causing errors
    - Negative values
    - Values exceeding max (default 86400 = 24 hours)
    """
    try:
        if value is None:
            return default
        
        # Handle string input
        if isinstance(value, str):
            value = float(value)
        
        # Check for NaN/Infinity
        if isinstance(value, float):
            if math.isnan(value) or math.isinf(value):
                logger.warning(f"Invalid numeric value: {value}, using default {default}")
                return default
        
        # Convert and clamp
        result = int(value)
        if result < min_val:
            logger.debug(f"Value {result} below min {min_val}, clamping")
            return min_val
        if result > max_val:
            logger.debug(f"Value {result} above max {max_val}, clamping")
            return max_val
        return result
        
    except (ValueError, TypeError) as e:
        logger.warning(f"Failed to convert to int: {value} - {e}")
        return default


def validate_span(span: dict, agent_id: str) -> Optional[str]:
    """
    Comprehensive server-side validation for screen time spans.
    Returns error message if invalid, None if valid.
    
    Special handling for capped spans (duration=86400) to accept
    legitimately capped long sessions while rejecting invalid data.
    """
    try:
        required = ['span_id', 'state', 'start_time', 'end_time', 'duration_seconds']
        for field in required:
            if field not in span:
                return f"Missing field: {field}"
        
        # 1. State validation
        if span['state'] not in ['active', 'idle', 'locked']:
            return f"Invalid state: {span['state']}"
            
        # 2. Time parsing and relative validation
        # We use parse_agent_timestamp which returns naive IST datetime
        start = parse_agent_timestamp(span['start_time'], agent_id)
        end = parse_agent_timestamp(span['end_time'], agent_id)
        
        if end < start:
            return "end_time before start_time"
            
        # 3. Duration validation
        calc_duration = (end - start).total_seconds()
        sent_duration = float(span['duration_seconds'])
        
        # Reject unrealistically long spans (> 24h)
        if sent_duration > 86400:
            return "Span duration exceeds 24 hours"

        if (
            span.get("state") == "active"
            and int(sent_duration) == RECOVERY_ACTIVE_SPAN_CAP_SECONDS
            and abs(calc_duration - RECOVERY_ACTIVE_SPAN_CAP_SECONDS) <= 1
        ):
            return (
                "Rejected probable capped recovery active span "
                f"({RECOVERY_ACTIVE_SPAN_CAP_SECONDS}s)"
            )
        
        # Special handling for capped spans (exactly 86400 seconds)
        # These are legitimately capped long sessions from crash recovery
        if sent_duration == 86400 and calc_duration >= 86400:
            # This is a capped span, accept it
            short_id = short_agent_id(agent_id)
            logger.info(
                f"[{short_id}] Accepting capped span: "
                f"calculated={calc_duration:.1f}s, sent=86400s"
            )
            return None
        
        # Normal validation: 5% tolerance for float rounding
        drift = abs(calc_duration - sent_duration)
        tolerance = sent_duration * 0.05  # 5% tolerance
        
        if drift > tolerance:
            return f"Duration mismatch: calculated {calc_duration}s vs sent {sent_duration}s (drift={drift:.1f}s, tolerance={tolerance:.1f}s)"
            
        return None
    except Exception as e:
        return f"Validation error: {str(e)}"


def safe_float(value, default=0.0, min_val=0.0, max_val=86400.0) -> float:
    """Safely convert value to float with validation."""
    try:
        if value is None:
            return default
        
        result = float(value)
        
        if math.isnan(result) or math.isinf(result):
            logger.warning(f"Invalid float value: {value}, using default {default}")
            return default
        
        if result < min_val:
            return min_val
        if result > max_val:
            return max_val
        return result
        
    except (ValueError, TypeError) as e:
        logger.warning(f"Failed to convert to float: {value} - {e}")
        return default


# =============================================================================
# TIMEZONE CONFIGURATION (IST)
# =============================================================================
from zoneinfo import ZoneInfo
IST = ZoneInfo("Asia/Kolkata")

def parse_agent_time(ts: str):
    """Normalize agent ISO timestamp to localized IST."""
    try:
        return datetime.fromisoformat(ts.replace('Z', '+00:00')).astimezone(IST)
    except Exception:
        return datetime.now(IST)

# ============================================================================
# LOGGING HELPERS
# ============================================================================
VERBOSE_TELEMETRY = False  # Set to True for detailed debugging

def short_agent_id(agent_id):
    """Return last 6 chars of agent ID for concise logging."""
    if not agent_id:
        return "??????"
    # Convert to string in case agent_id is an integer
    agent_id_str = str(agent_id)
    return agent_id_str[-6:] if len(agent_id_str) > 6 else agent_id_str

def store_raw_event(agent_id, event_type, payload, processed=False, error=None):
    """Store raw event payload for auditing and replay."""
    try:
        raw = server_models.RawEvent(
            agent_id=agent_id,
            event_type=event_type,
            sequence=payload.get('sequence'),
            payload=json.dumps(payload),
            received_at=datetime.now(get_server_tz()),
            processed=processed,
            error=error
        )
        db.session.add(raw)
        db.session.flush() # Ensure ID is generated
        return raw
    except Exception as e:
        # Reset failed transaction state after flush errors.
        db.session.rollback()
        logger.error(f"Failed to store raw event: {e}")
        return None

# ============================================================================
# TELEMETRY: SCREENTIME (LIVE - SOURCE OF TRUTH)
# ============================================================================
@bp.route('/screentime', methods=['POST'])
@require_auth
def telemetry_screentime():
    """
    ✅ AGENT-AUTHORITATIVE SCREEN TIME ENDPOINT
    
    This is the ONLY legal write path for screen_time table.
    
    DATA FLOW:
    1. Agent's state_machine.py calculates cumulative totals (ONLY place)
    2. Agent sends totals to this endpoint
    3. Server validates (non-negative, sum ≤ 86400)
    4. Server stores the incoming cumulative bucket set when the same-session
       total is non-regressing, preserving agent-side reclassification
       such as LOCKED -> AWAY after a continuous 2-hour lock.
    
    FORBIDDEN:
    - Server MUST NOT calculate, infer, recover, or repair screen time
    - Server MUST NOT aggregate spans into screen_time
    - Server MUST NOT compute deltas or durations
    - Server MUST NOT reconstruct or repair gaps
    
    CRITICAL: Under-counting is acceptable; fabricated time is forbidden.
    
    The agent is the single source of truth.
    
    Process screen time updates from Core's LiveTelemetryTracker.
    Accepts cumulative daily totals and persists the latest authoritative
    same-session bucket set.
    """
    data = request.get_json() or {}
    agent_id = str(g.current_agent.agent_id) if g.current_agent else None
    
    if not agent_id:
        return jsonify({'error': 'Missing agent_id'}), 400
    
    short_id = short_agent_id(agent_id)
    
    # Extract cumulative totals from Core
    active_seconds = safe_int(data.get('active_seconds', 0))
    idle_seconds = safe_int(data.get('idle_seconds', 0))
    locked_seconds = safe_int(data.get('locked_seconds', 0))
    away_seconds = safe_int(data.get('away_seconds', 0))
    current_state = data.get('current_state', 'active')
    session_start_str = data.get('session_start')  # Agent session start for reset detection
    total_seconds = active_seconds + idle_seconds + locked_seconds + away_seconds

    # Hard validation: cumulative daily buckets are mutually exclusive and must fit in one day.
    buckets = {
        "active_seconds": active_seconds,
        "idle_seconds": idle_seconds,
        "locked_seconds": locked_seconds,
        "away_seconds": away_seconds,
    }
    invalid_bucket = next(
        (
            (name, value)
            for name, value in buckets.items()
            if value < 0 or value > 86400
        ),
        None
    )
    if invalid_bucket:
        bucket_name, bucket_value = invalid_bucket
        logger.error(
            f"[{short_id}] screentime REJECTED: invalid {bucket_name}={bucket_value} "
            f"(must be 0..86400)"
        )
        return jsonify({'error': f'Invalid {bucket_name}: {bucket_value}'}), 400

    if total_seconds > 86400:
        logger.error(
            f"[{short_id}] screentime REJECTED: invalid total={total_seconds}s "
            f"(A={active_seconds}, I={idle_seconds}, L={locked_seconds}, W={away_seconds})"
        )
        return jsonify({'error': f'Invalid screentime total: {total_seconds} > 86400'}), 400
    
    logger.info(
        f"[{short_id}] screentime: active={active_seconds}s, "
        f"idle={idle_seconds}s, locked={locked_seconds}s, "
        f"away={away_seconds}s (state={current_state})"
    )
    
    # Store Raw Event
    raw_event = store_raw_event(agent_id, 'screentime', data, processed=False)
    
    try:
        # Parse timestamp
        ts_str = data.get('timestamp')
        if not ts_str:
            logger.error(f'[{short_id}] screentime REJECTED: missing timestamp')
            return jsonify({'error': 'Missing timestamp'}), 400

        is_final_day = data.get('is_final_day', False)
        final_day_date = data.get('final_day_date')
        logger.info(
            f"[{short_id}] [DIAG] screentime raw ts_str={ts_str!r}, "
            f"type={type(ts_str).__name__}, "
            f"active={data.get('active_seconds')}, idle={data.get('idle_seconds')}, "
            f"locked={data.get('locked_seconds')}, away={data.get('away_seconds')}, "
            f"is_final_day={is_final_day}, final_day_date={final_day_date!r}"
        )
        ts_naive = parse_agent_timestamp(ts_str, agent_id)

        if is_final_day:
            resolved_day = None
            if final_day_date:
                try:
                    resolved_day = datetime.fromisoformat(str(final_day_date)).date()
                except Exception:
                    logger.warning(
                        f"[{short_id}] Invalid final_day_date={final_day_date!r}; "
                        "falling back to timestamp-1day"
                    )
            if resolved_day is None:
                from datetime import timedelta
                resolved_day = (ts_naive - timedelta(days=1)).date()
            day = resolved_day
            ts_naive = datetime.combine(day, ts_naive.time())
            logger.info(f"[{short_id}] [DIAG] Final day data -> storing in date={day}")
        else:
            day = ts_naive.date()

        # Anomaly diagnostics only: detect strong regressions and overshoots from incoming totals.
        existing = server_models.ScreenTime.query.filter_by(agent_id=agent_id, date=day).first()
        if existing:
            if active_seconds + 1800 < (existing.active_seconds or 0):
                logger.warning(
                    f"[{short_id}] [ANOMALY] Active regression: incoming={active_seconds}, existing={existing.active_seconds}, day={day}"
                )
            if idle_seconds + 1800 < (existing.idle_seconds or 0):
                logger.warning(
                    f"[{short_id}] [ANOMALY] Idle regression: incoming={idle_seconds}, existing={existing.idle_seconds}, day={day}"
                )
            if locked_seconds + 1800 < (existing.locked_seconds or 0):
                logger.warning(
                    f"[{short_id}] [ANOMALY] Locked regression: incoming={locked_seconds}, existing={existing.locked_seconds}, day={day}"
                )
            if away_seconds + 1800 < (existing.away_seconds or 0):
                logger.warning(
                    f"[{short_id}] [ANOMALY] Away regression: incoming={away_seconds}, existing={existing.away_seconds}, day={day}"
                )
        
        # Parse session_start for reset detection
        session_start_naive = None
        if session_start_str:
            try:
                session_start_naive = parse_agent_timestamp(session_start_str, agent_id)
            except Exception:
                logger.warning(f"[{short_id}] Failed to parse session_start: {session_start_str}")
        
        # Call stored procedure to update screen_time table
        result = db.session.execute(
            text("""
                SELECT * FROM process_screentime_event(
                    :agent_id,
                    :timestamp,
                    :active,
                    :idle,
                    :locked,
                    :away,
                    :state,
                    :session_start
                )
            """),
            {
                'agent_id': agent_id,
                'timestamp': ts_naive,
                'active': active_seconds,
                'idle': idle_seconds,
                'locked': locked_seconds,
                'away': away_seconds,
                'state': current_state,
                'session_start': session_start_naive
            }
        ).fetchone()
        
        if result and result[0] == 'error':
            logger.error(f"[{short_id}] Stored procedure error: {result[1]}")
            raise Exception(result[1])
        
        # Update AgentCurrentStatus for live dashboard
        status = server_models.AgentCurrentStatus.query.filter_by(agent_id=agent_id).first()
        
        if status:
            status.current_state = current_state
            status.last_seen = ts_naive
        else:
            status = server_models.AgentCurrentStatus(
                agent_id=agent_id,
                current_state=current_state,
                last_seen=ts_naive
            )
            db.session.add(status)
        
        # Mark processed
        if raw_event:
            raw_event.processed = True
        
        # Track that agent is active
        update_telemetry_time(agent_id, pick_earliest_timestamp(session_start_naive, ts_naive))
        db.session.commit()
        
        return jsonify({'status': 'success'}), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"[{short_id}] screentime ERROR: {e}")
        
        # Log failure to RawEvent
        if raw_event:
            try:
                failed_raw = server_models.RawEvent(
                    agent_id=agent_id,
                    event_type='screentime',
                    sequence=data.get('sequence'),
                    payload=json.dumps(data),
                    received_at=datetime.now(get_server_tz()),
                    processed=False,
                    error=str(e)
                )
                db.session.add(failed_raw)
                db.session.commit()
            except:
                pass
        
        return jsonify({'error': str(e)}), 500



# ============================================================================
# TELEMETRY: APP-ACTIVE (LIVE LAYER)
# ============================================================================
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
    # CLEAN LOG: Only log if duration >= 1s
    short_id = short_agent_id(agent_id)
    duration = safe_int(data.get('duration_seconds', 0))
    if duration >= 1 or VERBOSE_TELEMETRY:
        logger.info(f"[{short_id}] app-active: {app} ({duration}s)")
    
    try:
        window_title = data.get('window_title')
        username = data.get('username')
        duration = safe_int(data.get('duration_seconds', 0))
        
        # BACKWARD COMPATIBLE STATE DETECTION
        # Try new format first (from production state detector)
        system_state = data.get('system_state')
        
        if system_state:
            # New agent with production state detector
            current_state = system_state
            logger.debug(f"[STATE] Using explicit system_state: {current_state}")
        else:
            # Old agent - infer state from 'state' field and app name
            old_state = data.get('state', 'active')
            
            # Define lock apps
            LOCK_APPS = ['lockapp.exe', 'logonui.exe', 'lockapp.exe', 'winlogon.exe']
            
            # Check if this is a lock app
            if app and app.lower() in [a.lower() for a in LOCK_APPS]:
                current_state = 'locked'
                logger.debug(f"[STATE] Detected lock from app name: {app}")
            elif old_state == 'idle':
                current_state = 'idle'
            else:
                current_state = 'active'
        
        # ✅ FIXED: Use parse_agent_timestamp for proper timezone handling
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
        
        # Update or create agent status
        status = server_models.AgentCurrentStatus.query.filter_by(agent_id=agent_id).first()
        
        if status:
            if status.current_app != app:
                status.session_start = session_start_naive
            status.current_app = app
            status.window_title = window_title
            status.duration_seconds = duration
            status.current_state = current_state  # Use detected state
            status.last_seen = timestamp_naive
            if username:
                status.username = username
        else:
            status = server_models.AgentCurrentStatus(
                agent_id=agent_id,
                username=username,
                current_app=app,
                window_title=window_title,
                current_state=current_state,  # Use detected state
                session_start=session_start_naive,
                duration_seconds=duration,
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


# ============================================================================
# TELEMETRY: DOMAIN-ACTIVE (LIVE LAYER)
# ============================================================================
@bp.route('/domain-active', methods=['POST'])
@require_auth
def telemetry_domain_active():
    """
    LIVE LAYER: Handle active domain telemetry (every 30s).
    
    Rule: Update agent_current_status with current domain info.
    Dashboard: Shows what domain/website each user is viewing NOW.
    
    Agent sends:
        domain, browser, url, session_start, duration_seconds, is_active, timestamp, username
    """
    data = request.get_json() or {}
    agent_id = str(g.current_agent.agent_id) if g.current_agent else None
    
    if not agent_id:
        return jsonify({'error': 'Missing agent_id'}), 400
    
    domain = data.get('domain')
    if not domain:
        # No domain is fine - agent sends this when no browser is active
        # Just return success silently
        return jsonify({'status': 'success', 'note': 'no domain'}), 200
    
    # CLEAN LOG: Concise one-liner
    short_id = short_agent_id(agent_id)
    duration = safe_int(data.get('duration_seconds', 0))
    logger.info(f"[{short_id}] domain-active: {domain} ({duration}s)")
    
    try:
        # Parse all fields from agent
        browser = data.get('browser')
        url = data.get('url')
        username = data.get('username')
        duration = safe_int(data.get('duration_seconds', 0))
        is_active = data.get('is_active', True)
        
        # ✅ FIXED: Use parse_agent_timestamp for proper timezone handling
        ts_str = data.get('timestamp', datetime.now(timezone.utc).isoformat())
        timestamp_naive = parse_agent_timestamp(ts_str, agent_id)
        
        # Parse session_start from agent (don't ignore it!)
        session_start_str = data.get('session_start')
        if session_start_str:
            try:
                session_start_naive = parse_agent_timestamp(session_start_str, agent_id)
            except:
                session_start_naive = timestamp_naive
        else:
            session_start_naive = timestamp_naive
        
        # ================================================================
        # LIVE LAYER: Update agent_current_status with domain info
        # ================================================================
        status = server_models.AgentCurrentStatus.query.filter_by(agent_id=agent_id).first()
        
        if status:
            # UPDATE existing row
            if status.current_domain != domain:
                # Domain changed - use session_start from agent
                status.domain_session_start = session_start_naive
            status.current_domain = domain
            status.current_browser = browser
            status.current_url = url
            status.domain_duration_seconds = duration  # Store domain duration!
            status.last_seen = timestamp_naive
            if username:
                status.username = username
        else:
            # CREATE first row for this agent
            status = server_models.AgentCurrentStatus(
                agent_id=agent_id,
                username=username,
                current_domain=domain,
                current_browser=browser,
                current_url=url,
                domain_session_start=session_start_naive,
                domain_duration_seconds=duration,
                last_seen=timestamp_naive
            )
            db.session.add(status)
        
        update_telemetry_time(agent_id, pick_earliest_timestamp(session_start_naive, timestamp_naive))
        db.session.commit()
        return jsonify({'status': 'success'}), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"[{short_id}] domain-active ERROR: {e}")
        return jsonify({'error': str(e)}), 500


# ============================================================================
# TELEMETRY: APP-SWITCH (HISTORICAL LAYER)
# ============================================================================
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
    
    # CLEAN LOG: Concise summary
    short_id = short_agent_id(agent_id)
    app = data.get('app', 'unknown')
    total_seconds = safe_int(data.get('total_seconds', 0))
    category = data.get('category', 'other')
    logger.info(f"[{short_id}] app-switch: {app} ({total_seconds}s, {category})")
    if VERBOSE_TELEMETRY:
        logger.debug(f"[{short_id}] app-switch FULL: {data}")
    
    # Store Raw Event
    raw_event = store_raw_event(agent_id, 'app-switch', data, processed=False)
    
    try:
        # Parse data
        app = data.get('app', 'unknown')
        friendly_name = data.get('friendly_name', app)
        category = data.get('category', 'other')
        window_title = data.get('window_title', '')
        total_seconds = safe_float(data.get('total_seconds', 0))
        
        # ✅ FIXED: Use parse_agent_timestamp for proper timezone handling
        ts_str = data.get('timestamp', datetime.now(timezone.utc).isoformat())
        start_str = data.get('session_start', datetime.now(get_server_tz()).isoformat())
        end_str = data.get('session_end', datetime.now(get_server_tz()).isoformat())
        
        timestamp_naive = parse_agent_timestamp(ts_str, agent_id)
        start_naive = parse_agent_timestamp(start_str, agent_id)
        end_naive = parse_agent_timestamp(end_str, agent_id)
        
        # ================================================================
        # Call stored procedure for ATOMIC processing with AUDIT
        # ================================================================
        from sqlalchemy import text
        
        result = db.session.execute(text("""
            SELECT * FROM process_app_switch_event(
                :agent_id, :timestamp, :app, :friendly_name, :category,
                :window_title, :session_start, :session_end, :total_seconds
            )
        """), {
            'agent_id': agent_id,
            'timestamp': timestamp_naive,
            'app': app,
            'friendly_name': friendly_name,
            'category': category,
            'window_title': window_title,
            'session_start': start_naive,
            'session_end': end_naive,
            'total_seconds': total_seconds
        })
        
        row = result.fetchone()
        
        # Mark processed
        if raw_event:
            raw_event.processed = True
            
        update_telemetry_time(agent_id, pick_earliest_timestamp(start_naive, end_naive, timestamp_naive))
        db.session.commit()
        
        # Handle stored procedure result:
        # - 'success' = processed successfully
        # - 'skipped' = rejected but not an error (e.g., duplicate, excessive duration)
        # - 'error' = actual error that should be retried
        if row:
            status = row[0]
            message = row[1] if len(row) > 1 else ''
            
            if status == 'success':
                return jsonify({'status': 'success'}), 200
            elif status == 'skipped':
                # Skipped events should return 200 so agent doesn't retry
                # (e.g., duplicates, excessive durations - these are expected rejections)
                logger.info(f"[{short_id}] app-switch skipped: {message}")
                return jsonify({'status': 'skipped', 'message': message}), 200
            else:
                # Actual error
                return jsonify({'status': 'error', 'message': message}), 500
        else:
            return jsonify({'status': 'error', 'message': 'No response from procedure'}), 500
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"[{short_id}] app-switch ERROR: {e}")
        
        # Log failure to RawEvent
        if raw_event:
            try:
                failed_raw = server_models.RawEvent(
                    agent_id=agent_id,
                    event_type='app-switch',
                    sequence=data.get('sequence'),
                    payload=json.dumps(data),
                    received_at=datetime.now(get_server_tz()),
                    processed=False,
                    error=str(e)
                )
                db.session.add(failed_raw)
                db.session.commit()
            except:
                pass
                
        return jsonify({'error': str(e)}), 500


# ============================================================================
# TELEMETRY: DOMAIN-SWITCH
# ============================================================================

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
    
    # CLEAN LOG: Concise summary
    short_id = short_agent_id(agent_id)
    domain = data.get('domain', 'unknown')
    total_seconds = safe_int(data.get('total_seconds', 0))
    browser = data.get('browser', '')
    logger.info(f"[{short_id}] domain-switch: {domain} ({total_seconds}s, {browser})")
    
    # Store Raw Event
    raw_event = store_raw_event(agent_id, 'domain-switch', data, processed=False)
    
    try:
        # Parse data
        domain = data.get('domain', 'unknown')
        browser = data.get('browser', '')
        url = data.get('url')
        total_seconds = safe_float(data.get('total_seconds', 0))
        
        # ✅ FIXED: Use parse_agent_timestamp for proper timezone handling
        ts_str = data.get('timestamp', datetime.now(timezone.utc).isoformat())
        start_str = data.get('session_start', datetime.now(get_server_tz()).isoformat())
        end_str = data.get('session_end', datetime.now(get_server_tz()).isoformat())
        
        timestamp_naive = parse_agent_timestamp(ts_str, agent_id)
        start_naive = parse_agent_timestamp(start_str, agent_id)
        end_naive = parse_agent_timestamp(end_str, agent_id)
        
        # ================================================================
        # Call stored procedure for ATOMIC processing with AUDIT
        # ================================================================
        from sqlalchemy import text
        
        # Get username from current agent or use None
        username = g.current_agent.username if hasattr(g.current_agent, 'username') else None
        
        # Call stored procedure with correct parameter signature
        result = db.session.execute(text("""
            SELECT * FROM process_domain_switch_event(
                :agent_id, :username, :domain, :raw_title, :raw_url, :browser,
                :session_start, :session_end, :duration_seconds, :idempotency_key
            )
        """), {
            'agent_id': agent_id,
            'username': username,
            'domain': domain,
            'raw_title': None,  # Not provided in domain-switch event
            'raw_url': url,
            'browser': browser,
            'session_start': start_naive,
            'session_end': end_naive,
            'duration_seconds': int(total_seconds),  # Procedure expects integer
            'idempotency_key': None
        })
        
        row = result.fetchone()
        
        # Mark processed
        if raw_event:
            raw_event.processed = True
            
        update_telemetry_time(str(agent_id), pick_earliest_timestamp(start_naive, end_naive, timestamp_naive))
        db.session.commit()
        
        # Handle stored procedure result (same logic as app-switch)
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
        
        # Log failure to RawEvent
        if raw_event:
            try:
                failed_raw = server_models.RawEvent(
                    agent_id=agent_id,
                    event_type='domain-switch',
                    sequence=data.get('sequence'),
                    payload=json.dumps(data),
                    received_at=datetime.now(get_server_tz()),
                    processed=False,
                    error=str(e)
                )
                db.session.add(failed_raw)
                db.session.commit()
            except:
                pass
                
        return jsonify({'error': str(e)}), 500




# ============================================================================
# TELEMETRY: STATE-CHANGE
# ============================================================================
@bp.route('/state-change', methods=['POST'])
@require_auth
def telemetry_state_change():
    """Handle state change event (active/idle/locked) with duration tracking and AWAY classification."""
    data = request.get_json() or {}
    agent_id = g.current_agent.agent_id if g.current_agent else None
    
    if not agent_id:
        return jsonify({'error': 'Missing agent_id'}), 400
    
    # CLEAN LOG: Concise state transition
    short_id = short_agent_id(agent_id)
    previous_state = data.get('previous_state', 'unknown')
    current_state = data.get('current_state', 'unknown')
    duration = safe_float(data.get('duration_seconds', 0))
    logger.info(f"[{short_id}] state-change: {previous_state}→{current_state} (Δ{int(duration)}s)")
    
    # Store Raw Event
    raw_event = store_raw_event(agent_id, 'state-change', data, processed=False)
    
    try:
        # ✅ FIXED: Use parse_agent_timestamp for proper timezone handling
        ts_str = data.get('timestamp')
        if not ts_str:
            logger.error(f'[{short_id}] screentime REJECTED: missing timestamp')
            return jsonify({'error': 'Missing timestamp'}), 400
        ts_naive = parse_agent_timestamp(ts_str, agent_id)
        
        previous_state = data.get('previous_state', 'unknown')
        current_state = data.get('current_state', 'unknown')
        
        # Create state change record
        state_change = server_models.StateChange(
            agent_id=agent_id,
            username=data.get('username'),
            previous_state=previous_state,
            current_state=current_state,
            timestamp=ts_naive
        )
        db.session.add(state_change)
        
        # DONE: Agent now handles Away classification. 
        # Server simply stores what it receives.
        
        # Mark processed
        if raw_event:
            raw_event.processed = True
            
        update_telemetry_time(agent_id, ts_naive)
        db.session.commit()
        
        return jsonify({'status': 'success'}), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"[{short_id}] state-change ERROR: {e}")
        
        # Log failure to RawEvent
        if raw_event:
            try:
                failed_raw = server_models.RawEvent(
                    agent_id=agent_id,
                    event_type='state-change',
                    sequence=data.get('sequence'),
                    payload=json.dumps(data),
                    received_at=datetime.now(get_server_tz()),
                    processed=False,
                    error=str(e)
                )
                db.session.add(failed_raw)
                db.session.commit()
            except:
                pass
                
        return jsonify({'error': str(e)}), 500


@bp.route('/event', methods=['POST'])
@require_auth
def telemetry_event():
    """
    Generic telemetry event receiver.
    Routes events to specific handlers based on 'type' or 'event' field.
    """
    data = request.get_json() or {}
    agent_id = g.current_agent.agent_id if g.current_agent else None
    
    if not agent_id:
        return jsonify({'error': 'Missing agent_id'}), 400
    
    event_type = data.get('type') or data.get('event')
    short_id = short_agent_id(agent_id)
    
    if event_type == 'state_duration_event' or event_type == 'state_duration':
        return handle_state_duration_event(agent_id, data)
    
    logger.info(f"[{short_id}] Received unknown event type: {event_type}")
    return jsonify({'status': 'ignored', 'message': f'Unknown event type: {event_type}'}), 200

def handle_state_duration_event(agent_id, data):
    """
    HTTP wrapper for state-duration payloads.
    Injects authenticated agent_id and returns a Flask response.
    """
    payload = dict(data or {})
    payload["agent_id"] = str(agent_id)
    return process_state_duration_event(payload)


def handle_state_duration(agent_id, data):
    """
    Backward-compatible alias used by background reprocessing.
    """
    return handle_state_duration_event(agent_id, data)


def process_state_duration_event(payload: dict):
    """
    AUTHORITATIVE Event Handler (Step 367).
    Processes state_duration events as the SINGLE SOURCE OF TRUTH.
    """
    from sqlalchemy import text
    agent_id = payload.get("agent_id")
    if not agent_id:
        return jsonify({"error": "Missing agent_id"}), 400
    short_id = short_agent_id(agent_id)
    state = payload.get("state")
    duration = safe_float(payload.get("duration_seconds", 0))
    ts_str = payload.get("timestamp")
    
    if not state or duration <= 0:
        logger.info(f"[{short_id}] Dropping invalid event: {state} {duration}s")
        return jsonify({"status": "ignored"}), 200

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
        return jsonify({"status": "ignored", "reason": "unknown_state"}), 200

    try:
        # Step 4.3: IST Normalization
        timestamp = parse_agent_time(ts_str) if ts_str else datetime.now(get_server_tz())
        
        # Step 4.2: Call the additive procedure
        db.session.execute(
            text("""
                SELECT * FROM process_screentime_delta(
                    :agent_id,
                    :timestamp,
                    :active,
                    :idle,
                    :locked,
                    :state,
                    :away
                )
            """),
            {
                "agent_id": agent_id,
                "timestamp": timestamp,
                "active": int(delta_active),
                "idle": int(delta_idle),
                "locked": int(delta_locked),
                "state": state,
                "away": int(delta_away),
            }
        )
        
        db.session.commit()
        logger.info(f"[{short_id}] Processed state_duration: {state} +{duration:.1f}s (IST: {timestamp.strftime('%H:%M')})")
        return jsonify({"status": "success"}), 200

    except Exception as e:
        db.session.rollback()
        logger.error(f"[{short_id}] process_state_duration ERROR: {e}")
        return jsonify({"error": str(e)}), 500


# ============================================================================
# TELEMETRY: SCREENTIME SPANS (IDEMPOTENT SOURCE OF TRUTH)
# ============================================================================
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
    
    # Store Raw Event for audit
    store_raw_event(agent_id, 'screentime-spans', data)
    
    stored_count = 0
    duplicate_count = 0
    batch_earliest: Optional[datetime] = None
    errors = []
    
    try:
        for span in spans:
            # 1. Validate
            val_error = validate_span(span, agent_id)
            if val_error:
                logger.warning(f"[{short_id}] Invalid span {span.get('span_id')}: {val_error}")
                errors.append({"span_id": span.get('span_id'), "error": val_error})
                continue
                
            # 2. Parse times for DB
            start = parse_agent_timestamp(span['start_time'], agent_id)
            end = parse_agent_timestamp(span['end_time'], agent_id)
            batch_earliest = pick_earliest_timestamp(batch_earliest, start, end)
            
            # 3. Idempotent Insert
            # We use text() with ON CONFLICT for performance and correctness
            insert_result = db.session.execute(text("""
                INSERT INTO screen_time_spans (
                    span_id, agent_id, state, start_time, end_time, duration_seconds
                ) VALUES (
                    :span_id, :agent_id, :state, :start, :end, :duration
                ) ON CONFLICT (span_id) DO NOTHING
            """), {
                'span_id': span['span_id'],
                'agent_id': agent_id,
                'state': span['state'],
                'start': start,
                'end': end,
                'duration': int(span['duration_seconds'])
            })
            if insert_result.rowcount and insert_result.rowcount > 0:
                stored_count += 1
            else:
                duplicate_count += 1
            
        update_telemetry_time(agent_id, batch_earliest)
        db.session.commit()
        
        return jsonify({
            'status': 'success',
            'count': stored_count,
            'stored': stored_count,
            'duplicates': duplicate_count,
            'rejected': len(errors),
            'total': len(spans),
            'errors': errors if errors else None
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"[{short_id}] screentime-spans ERROR: {e}")
        return jsonify({'error': str(e)}), 500


# ============================================================================
# ROOT-LEVEL TELEMETRY ENDPOINTS
# ============================================================================
def register_root_telemetry_endpoints(app):
    """Register telemetry endpoints at root level for agent compatibility."""
    
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

    @app.route('/telemetry/event', methods=['POST'])
    @require_auth
    def root_telemetry_event():
        """Backward-compat alias: proxies to /api/v1/telemetry/event"""
        return telemetry_event()
