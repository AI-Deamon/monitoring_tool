"""
Telemetry Package — Endpoint modules for all telemetry data processing.

Re-exports the Blueprint and helper functions for backward compatibility.

Usage (unchanged):
    from server_telemetry import bp
    # or
    from telemetry import bp
    from telemetry.helpers import parse_agent_timestamp
"""
from telemetry.helpers import (
    get_server_tz, pick_earliest_timestamp, update_telemetry_time,
    parse_agent_timestamp, safe_int, safe_float, validate_span,
    parse_agent_time, short_agent_id, store_raw_event,
    SERVER_TIMEZONE, IST, VERBOSE_TELEMETRY,
    _PYTZ_AVAILABLE,
)

# Import the blueprint and all endpoint functions
from telemetry.screentime import bp
from telemetry.screentime import telemetry_screentime

from telemetry.app_events import telemetry_app_active, telemetry_app_switch
from telemetry.domain_events import telemetry_domain_active, telemetry_domain_switch
from telemetry.state_spans import (
    telemetry_state_change, telemetry_event,
    process_state_duration_event, telemetry_screentime_spans,
    register_root_telemetry_endpoints,
)

__all__ = [
    'bp',
    'telemetry_screentime', 'telemetry_app_active', 'telemetry_app_switch',
    'telemetry_domain_active', 'telemetry_domain_switch',
    'telemetry_state_change', 'telemetry_event',
    'process_state_duration_event', 'telemetry_screentime_spans',
    'register_root_telemetry_endpoints',
    'get_server_tz', 'pick_earliest_timestamp', 'update_telemetry_time',
    'parse_agent_timestamp', 'safe_int', 'safe_float', 'validate_span',
    'parse_agent_time', 'short_agent_id', 'store_raw_event',
    'SERVER_TIMEZONE', 'IST', 'VERBOSE_TELEMETRY',
]
