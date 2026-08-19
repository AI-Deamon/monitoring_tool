"""
Agent-local time — the single source of truth for the agent's UTC offset.

Every module that decides "what day is it for this user" must agree, or the
same activity lands on different dates in different tables. The offset was
previously hardcoded as IST (+05:30) in four separate places (buffer,
state_machine, state_detector, live_telemetry); this module centralizes it.

Default is IST (330 minutes) so existing deployments are unchanged. Override
per-deployment with:
    - config.json  agent.timezone_offset_minutes
    - env var      AGENT_TZ_OFFSET_MINUTES
"""

import logging
import os
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

DEFAULT_OFFSET_MINUTES = 330  # IST (+05:30)

_offset_minutes = DEFAULT_OFFSET_MINUTES
_tz = timezone(timedelta(minutes=DEFAULT_OFFSET_MINUTES), name="AGENT_LOCAL")


def _coerce(minutes) -> int:
    value = int(minutes)
    if not -14 * 60 <= value <= 14 * 60:
        raise ValueError(f"offset out of range: {value}")
    return value


def set_offset_minutes(minutes) -> None:
    """Reconfigure the agent-local UTC offset (called once at config load)."""
    global _offset_minutes, _tz
    try:
        value = _coerce(minutes)
    except (TypeError, ValueError) as e:
        logger.warning(
            f"[TIME] Invalid timezone_offset_minutes {minutes!r} ({e}) - "
            f"keeping {_offset_minutes}"
        )
        return
    _offset_minutes = value
    _tz = timezone(timedelta(minutes=value), name="AGENT_LOCAL")
    logger.info(f"[TIME] Agent-local offset set to {value} minutes from UTC")


def get_offset_minutes() -> int:
    return _offset_minutes


def get_timezone() -> timezone:
    return _tz


def now() -> datetime:
    """Current time in agent-local time (tz-aware)."""
    return datetime.now(_tz)


def to_local(dt: datetime) -> datetime:
    """Convert a datetime to agent-local time (naive input assumed UTC)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_tz)


def today():
    """The current *local* calendar date - the agent's day boundary."""
    return now().date()


# Environment override applies at import so early callers see it too.
_env = os.getenv('AGENT_TZ_OFFSET_MINUTES')
if _env:
    set_offset_minutes(_env)
