"""
Telemetry Helpers: Timezone handling, parsing, validation, and logging utilities.
Shared across all telemetry endpoint modules.
"""
import logging
import json
import math
from datetime import datetime, date, timezone, timedelta
from typing import Optional
from extensions import db
from zoneinfo import ZoneInfo

# Try to import pytz for timezone handling
try:
    import pytz
    _PYTZ_AVAILABLE = True
except ImportError:
    _PYTZ_AVAILABLE = False

logger = logging.getLogger(__name__)

# Server timezone (matches PostgreSQL stored procedures)
SERVER_TIMEZONE = 'Asia/Kolkata'
IST = ZoneInfo("Asia/Kolkata")

# Logging configuration
VERBOSE_TELEMETRY = False  # Set to True for detailed debugging


def get_server_tz():
    """Get server timezone object."""
    if _PYTZ_AVAILABLE:
        return pytz.timezone(SERVER_TIMEZONE)
    else:
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
        import server_models
        agent = server_models.Agent.query.filter_by(agent_id=agent_id).first()
        if agent:
            agent.last_telemetry_time = datetime.utcnow()
            if event_timestamp is not None:
                if not agent.first_activity_at or event_timestamp < agent.first_activity_at:
                    agent.first_activity_at = event_timestamp
    except Exception as e:
        logger.warning(f"Failed to update telemetry time for {short_agent_id(agent_id)}: {e}")


def parse_agent_timestamp(ts_str: str, agent_id: str = None) -> datetime:
    """
    Parse and normalize agent timestamps with robust timezone handling.

    - New agents (v1.2+): Send IST timestamp with +05:30
    - Old agents (v1.0-1.1): Send UTC timestamp with Z

    Returns: Naive datetime in server timezone (IST)
    """
    short_id = short_agent_id(agent_id) if agent_id else "??????"

    try:
        if not ts_str or not isinstance(ts_str, str) or not ts_str.strip():
            raise ValueError("Invalid timestamp format")

        ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))

        if ts.tzinfo is None:
            logger.warning(f"[{short_id}] Legacy timestamp without timezone: {ts_str}")
            ts = ts.replace(tzinfo=timezone.utc)

        now = datetime.now(timezone.utc)
        max_future = now + timedelta(hours=2)
        min_past = now - timedelta(days=365)

        if ts > max_future:
            logger.warning(f"[{short_id}] Timestamp too far in future: {ts_str}")
            return now.astimezone(get_server_tz()).replace(tzinfo=None)
        if ts < min_past:
            logger.warning(f"[{short_id}] Timestamp too old: {ts_str}")
            raise ValueError("Timestamp outside valid range")

        server_tz = get_server_tz()
        ts_local = ts.astimezone(server_tz)
        return ts_local.replace(tzinfo=None)

    except Exception as e:
        logger.error(f"[{short_id}] Failed to parse timestamp: {ts_str} - {e}")
        if _PYTZ_AVAILABLE:
            return datetime.now(pytz.timezone(SERVER_TIMEZONE)).replace(tzinfo=None)
        else:
            return datetime.now(timezone.utc).replace(tzinfo=None)


def safe_int(value, default=0, min_val=0, max_val=86400) -> int:
    """Safely convert value to integer with validation."""
    try:
        if value is None:
            return default
        if isinstance(value, str):
            value = float(value)
        if isinstance(value, float):
            if math.isnan(value) or math.isinf(value):
                logger.warning(f"Invalid numeric value: {value}, using default {default}")
                return default
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

        if span['state'] not in ['active', 'idle', 'locked']:
            return f"Invalid state: {span['state']}"

        start = parse_agent_timestamp(span['start_time'], agent_id)
        end = parse_agent_timestamp(span['end_time'], agent_id)

        if end < start:
            return "end_time before start_time"

        calc_duration = (end - start).total_seconds()
        sent_duration = float(span['duration_seconds'])

        if sent_duration > 86400:
            return "Span duration exceeds 24 hours"

        if sent_duration == 86400 and calc_duration >= 86400:
            short_id = short_agent_id(agent_id)
            logger.info(
                f"[{short_id}] Accepting capped span: "
                f"calculated={calc_duration:.1f}s, sent=86400s"
            )
            return None

        drift = abs(calc_duration - sent_duration)
        tolerance = sent_duration * 0.05

        if drift > tolerance:
            return f"Duration mismatch: calculated {calc_duration}s vs sent {sent_duration}s (drift={drift:.1f}s, tolerance={tolerance:.1f}s)"

        return None
    except Exception as e:
        return f"Validation error: {str(e)}"


def parse_agent_time(ts: str):
    """Normalize agent ISO timestamp to localized IST."""
    try:
        return datetime.fromisoformat(ts.replace('Z', '+00:00')).astimezone(IST)
    except Exception:
        return datetime.now(IST)


def short_agent_id(agent_id):
    """Return last 6 chars of agent ID for concise logging."""
    if not agent_id:
        return "??????"
    agent_id_str = str(agent_id)
    return agent_id_str[-6:] if len(agent_id_str) > 6 else agent_id_str


def store_raw_event(agent_id, event_type, payload, processed=False, error=None):
    """Store raw event payload for auditing and replay."""
    try:
        import server_models
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
        db.session.flush()
        return raw
    except Exception as e:
        logger.error(f"Failed to store raw event: {e}")
        return None
