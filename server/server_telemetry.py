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


def update_telemetry_time(agent_id: str):
    """
    Update last_telemetry_time for an agent when actual telemetry data is received.
    This is different from last_seen which is updated on any authenticated request.
    
    Used to detect "silent failures" - agents that are online but not sending data.
    """
    try:
        agent = server_models.Agent.query.filter_by(agent_id=agent_id).first()
        if agent:
            agent.last_telemetry_time = datetime.utcnow()
            # Don't commit here - let the calling function handle the commit
    except Exception as e:
        logger.warning(f"Failed to update telemetry time for {short_agent_id(agent_id)}: {e}")


def parse_agent_timestamp(ts_str: str, agent_id: str = None) -> datetime:
    """
    Parse timestamp from agent with backward compatibility and VALIDATION.
    
    - New agents (v1.2+): Send IST timestamp with +05:30
    - Old agents (v1.0-1.1): Send UTC timestamp with Z
    
    Bug #5 Fix: Added validation to reject unreasonable timestamps.
    
    Returns: Naive datetime in server timezone (IST)
    """
    short_id = short_agent_id(agent_id) if agent_id else "??????"
    
    try:
        # Parse ISO format
        ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
        
        if ts.tzinfo is None:
            # No timezone info - assume UTC (legacy agent)
            logger.debug(f"[{short_id}] Legacy timestamp (no TZ): {ts_str}")
            ts = ts.replace(tzinfo=timezone.utc)
        
        # ================================================================
        # Bug #5 Fix: Validate timestamp is within reasonable range
        # ================================================================
        now = datetime.now(timezone.utc)
        
        # Reject timestamps too far in the past (> 365 days)
        if ts < now - timedelta(days=365):
            logger.warning(f"[{short_id}] Timestamp too old (>1 year): {ts_str}")
            raise ValueError(f"Timestamp too far in past: {ts_str}")
        
        # FIX 7: Allow 24h backfill, clamp minor clock drift
        if ts > now + timedelta(hours=24):
            # Too far in future - reject
            logger.warning(f"[{short_id}] Timestamp too far future: {ts_str}")
            raise ValueError(f"Timestamp too far future: {ts_str}")
        elif ts > now + timedelta(hours=1):
            # Minor future timestamp (clock drift) - clamp to now
            logger.debug(f"[{short_id}] Minor future timestamp (clock drift): {ts_str}, clamping to now")
            ts = now
        
        # Convert to server timezone
        server_tz = get_server_tz()
        if _PYTZ_AVAILABLE:
            ts_local = ts.astimezone(server_tz)
        else:
            ts_local = ts.astimezone(server_tz)
        
        # Return naive datetime in server timezone (for PostgreSQL)
        return ts_local.replace(tzinfo=None)
        
    except ValueError:
        # Re-raise validation errors
        raise
    except Exception as e:
        logger.error(f"[{short_id}] Failed to parse timestamp: {ts_str} - {e}")
        # Fallback: use current server time
        if _PYTZ_AVAILABLE:
            return datetime.now(pytz.timezone(SERVER_TIMEZONE)).replace(tzinfo=None)
        else:
            return datetime.now(timezone.utc).replace(tzinfo=None)


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
        
        # Allow small margin (1s) for float ceiling/rounding during transfer
        if abs(calc_duration - sent_duration) > 1.1:
             return f"Duration mismatch: calculated {calc_duration}s vs sent {sent_duration}s"
             
        # Reject unrealistically long spans (> 24h)
        if sent_duration > 86400:
            return "Span duration exceeds 24 hours"
            
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
            received_at=datetime.utcnow(),
            processed=processed,
            error=error
        )
        db.session.add(raw)
        db.session.flush() # Ensure ID is generated
        return raw
    except Exception as e:
        logger.error(f"Failed to store raw event: {e}")
        return None

# ============================================================================
# TELEMETRY: SCREENTIME (LIVE - SOURCE OF TRUTH)
# ============================================================================
@bp.route('/screentime', methods=['POST'])
@require_auth
def telemetry_screentime():
    """
    Process screen time updates from Core's LiveTelemetryTracker.
    Accepts cumulative daily totals and uses GREATEST() for monotonic values.
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
    current_state = data.get('current_state', 'active')
    
    logger.info(
        f"[{short_id}] screentime: active={active_seconds}s, "
        f"idle={idle_seconds}s, locked={locked_seconds}s (state={current_state})"
    )
    
    # Store Raw Event
    raw_event = store_raw_event(agent_id, 'screentime', data, processed=False)
    
    try:
        # Parse timestamp
        ts_str = data.get('timestamp', datetime.utcnow().isoformat())
        ts_naive = parse_agent_timestamp(ts_str, agent_id)
        
        # Call stored procedure to update screen_time table
        result = db.session.execute(
            text("""
                SELECT * FROM process_screentime_event(
                    :agent_id,
                    :timestamp,
                    :active,
                    :idle,
                    :locked,
                    :state
                )
            """),
            {
                'agent_id': agent_id,
                'timestamp': ts_naive,
                'active': active_seconds,
                'idle': idle_seconds,
                'locked': locked_seconds,
                'state': current_state
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
        update_telemetry_time(agent_id)
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
                    received_at=datetime.utcnow(),
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
        start_str = data.get('session_start', datetime.utcnow().isoformat())
        end_str = data.get('session_end', datetime.utcnow().isoformat())
        
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
                    received_at=datetime.utcnow(),
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
        start_str = data.get('session_start', datetime.utcnow().isoformat())
        end_str = data.get('session_end', datetime.utcnow().isoformat())
        
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
                    received_at=datetime.utcnow(),
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
        ts_str = data.get('timestamp', datetime.utcnow().isoformat())
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
        
        # ============================================================================
        # AWAY TIME CLASSIFICATION
        # When transitioning FROM locked state, check if duration >= 2 hours (7200s)
        # If so, this is "away" time (user was away from computer)
        # Otherwise, it's just "locked" time (short lock, e.g., bathroom break)
        # ============================================================================
        AWAY_THRESHOLD_SECONDS = 7200  # 2 hours
        
        if previous_state == 'locked' and duration >= AWAY_THRESHOLD_SECONDS:
            # Classify this as AWAY time
            logger.info(f"[{short_id}] 📍 AWAY detected: locked for {duration/3600:.1f}h (>2h threshold)")
            
            # Update screen_time: move this locked duration to away_seconds
            today = ts_naive.date()
            screen_time = server_models.ScreenTime.query.filter_by(
                agent_id=agent_id,
                date=today
            ).first()
            
            if screen_time:
                # Transfer time from locked_seconds to away_seconds
                # The cumulative locked_seconds from agent includes this period,
                # so we track how much should be "away" separately
                transfer_amount = int(duration)
                
                # Ensure we don't go negative on locked_seconds
                current_locked = screen_time.locked_seconds or 0
                actual_transfer = min(transfer_amount, current_locked)
                
                if actual_transfer > 0:
                    screen_time.locked_seconds = current_locked - actual_transfer
                    screen_time.away_seconds = (screen_time.away_seconds or 0) + actual_transfer
                    screen_time.last_updated = datetime.utcnow()
                    
                    logger.info(
                        f"[{short_id}] away_seconds updated: "
                        f"locked={screen_time.locked_seconds}s (-{actual_transfer}s), "
                        f"away={screen_time.away_seconds}s (+{actual_transfer}s)"
                    )
            else:
                # Screen time record doesn't exist yet, will be created by screentime endpoint
                # Just log for now
                logger.debug(f"[{short_id}] Screen time record not found for {today}, away classification pending")
        
        # Mark processed
        if raw_event:
            raw_event.processed = True
            
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
                    received_at=datetime.utcnow(),
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

def process_state_duration_event(payload: dict):
    """
    AUTHORITATIVE Event Handler (Step 367).
    Processes state_duration events as the SINGLE SOURCE OF TRUTH.
    """
    from sqlalchemy import text
    agent_id = payload["agent_id"]
    short_id = short_agent_id(agent_id)
    state = payload.get("state")
    duration = safe_float(payload.get("duration_seconds", 0))
    ts_str = payload.get("timestamp")
    
    if not state or duration <= 0:
        logger.info(f"[{short_id}] Dropping invalid event: {state} {duration}s")
        return

    # Away-time classification (Step 367 rule: locked > 7200s -> away_seconds)
    delta_active = delta_idle = delta_locked = delta_away = 0
    if state == "active":
        delta_active = duration
    elif state == "idle":
        delta_idle = duration
    elif state == "locked":
        if duration >= 7200:
            delta_away = duration
        else:
            delta_locked = duration

    try:
        # Step 4.3: IST Normalization
        timestamp = parse_agent_time(ts_str)
        
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

    except Exception as e:
        db.session.rollback()
        logger.error(f"[{short_id}] process_state_duration ERROR: {e}")


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
            
            # 3. Idempotent Insert
            # We use text() with ON CONFLICT for performance and correctness
            db.session.execute(text("""
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
            stored_count += 1
            
        db.session.commit()
        update_telemetry_time(agent_id)
        
        return jsonify({
            'status': 'success',
            'count': stored_count,
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

    # @app.route('/telemetry/event', methods=['POST'])
    # @require_auth
    # def root_telemetry_event():
    #     """Handled by telemetry_api blueprint in server_api.py (Step 5)"""
    #     return telemetry_event()
