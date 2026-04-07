"""
Telemetry: Screentime Endpoint
Defines the Blueprint and handles /api/v1/telemetry/screentime
"""

import logging
import json
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, g
from sqlalchemy import text
from extensions import db
import server_models
from server_auth import require_auth
from pydantic import ValidationError
from schemas import ScreentimeSchema

from telemetry.helpers import (
    short_agent_id,
    safe_int,
    parse_agent_timestamp,
    pick_earliest_timestamp,
    update_telemetry_time,
    store_raw_event,
    VERBOSE_TELEMETRY,
)

logger = logging.getLogger(__name__)

# The single Blueprint shared across all telemetry modules
bp = Blueprint("telemetry", __name__)


@bp.route("/screentime", methods=["POST"])
@require_auth
def telemetry_screentime():
    """
    ✅ AGENT-AUTHORITATIVE SCREEN TIME ENDPOINT

    This is the ONLY legal write path for screen_time table.

    DATA FLOW:
    1. Agent's state_machine.py calculates cumulative totals (ONLY place)
    2. Agent sends totals to this endpoint
    3. Server validates (non-negative, sum ≤ 86400)
    4. Server stores via GREATEST() (monotonic, no regression)

    FORBIDDEN:
    - Server MUST NOT calculate, infer, recover, or repair screen time
    - Server MUST NOT aggregate spans into screen_time
    - Server MUST NOT compute deltas or durations
    - Server MUST NOT reconstruct or repair gaps

    CRITICAL: Under-counting is acceptable; fabricated time is forbidden.
    The agent is the single source of truth.
    """
    data = request.get_json() or {}
    agent_id = str(g.current_agent.agent_id) if g.current_agent else None

    if not agent_id:
        return jsonify({"error": "Missing agent_id"}), 400

    short_id = short_agent_id(agent_id)

    # Extract cumulative totals from Core
    active_seconds = safe_int(data.get("active_seconds", 0))
    idle_seconds = safe_int(data.get("idle_seconds", 0))
    locked_seconds = safe_int(data.get("locked_seconds", 0))
    away_seconds = safe_int(data.get("away_seconds", 0))
    current_state = data.get("current_state", "active")
    session_start_str = data.get("session_start")
    total_seconds = active_seconds + idle_seconds + locked_seconds + away_seconds

    # Hard validation
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
        None,
    )
    if invalid_bucket:
        bucket_name, bucket_value = invalid_bucket
        logger.error(
            f"[{short_id}] screentime REJECTED: invalid {bucket_name}={bucket_value} "
            f"(must be 0..86400)"
        )
        return jsonify({"error": f"Invalid {bucket_name}: {bucket_value}"}), 400

    if total_seconds > 86400:
        logger.error(
            f"[{short_id}] screentime REJECTED: invalid total={total_seconds}s "
            f"(A={active_seconds}, I={idle_seconds}, L={locked_seconds}, W={away_seconds})"
        )
        return jsonify(
            {"error": f"Invalid screentime total: {total_seconds} > 86400"}
        ), 400

    logger.info(
        f"[{short_id}] screentime: active={active_seconds}s, "
        f"idle={idle_seconds}s, locked={locked_seconds}s, "
        f"away={away_seconds}s (state={current_state})"
    )

    raw_event = store_raw_event(agent_id, "screentime", data, processed=False)

    try:
        ts_str = data.get("timestamp", datetime.utcnow().isoformat())
        is_final_day = data.get("is_final_day", False)
        logger.info(
            f"[{short_id}] [DIAG] screentime raw ts_str={ts_str!r}, "
            f"type={type(ts_str).__name__}, "
            f"active={data.get('active_seconds')}, idle={data.get('idle_seconds')}, "
            f"locked={data.get('locked_seconds')}, away={data.get('away_seconds')}, "
            f"is_final_day={is_final_day}"
        )
        ts_naive = parse_agent_timestamp(ts_str, agent_id)

        # If this is final day data (from midnight boundary), use YESTERDAY's date
        if is_final_day:
            from datetime import timedelta

            day = (ts_naive - timedelta(days=1)).date()
            logger.info(
                f"[{short_id}] [DIAG] Final day data → storing in yesterday: {day}"
            )
        else:
            day = ts_naive.date()

        # Anomaly diagnostics
        existing = server_models.ScreenTime.query.filter_by(
            agent_id=agent_id, date=day
        ).first()
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

        session_start_naive = None
        if session_start_str:
            try:
                session_start_naive = parse_agent_timestamp(session_start_str, agent_id)
            except Exception:
                logger.warning(
                    f"[{short_id}] Failed to parse session_start: {session_start_str}"
                )

        result = db.session.execute(
            text("""
                SELECT * FROM process_screentime_event(
                    :agent_id, :timestamp, :active, :idle, :locked, :away, :state, :session_start
                )
            """),
            {
                "agent_id": agent_id,
                "timestamp": ts_naive,
                "active": active_seconds,
                "idle": idle_seconds,
                "locked": locked_seconds,
                "away": away_seconds,
                "state": current_state,
                "session_start": session_start_naive,
            },
        ).fetchone()

        if result and result[0] == "error":
            logger.error(f"[{short_id}] Stored procedure error: {result[1]}")
            raise Exception(result[1])

        status = server_models.AgentCurrentStatus.query.filter_by(
            agent_id=agent_id
        ).first()
        if status:
            status.current_state = current_state
            status.last_seen = ts_naive
        else:
            status = server_models.AgentCurrentStatus(
                agent_id=agent_id, current_state=current_state, last_seen=ts_naive
            )
            db.session.add(status)

        if raw_event:
            raw_event.processed = True

        update_telemetry_time(
            agent_id, pick_earliest_timestamp(session_start_naive, ts_naive)
        )
        db.session.commit()
        return jsonify({"status": "success"}), 200

    except Exception as e:
        db.session.rollback()
        logger.error(f"[{short_id}] screentime ERROR: {e}")
        if raw_event:
            try:
                failed_raw = server_models.RawEvent(
                    agent_id=agent_id,
                    event_type="screentime",
                    sequence=data.get("sequence"),
                    payload=json.dumps(data),
                    received_at=datetime.utcnow(),
                    processed=False,
                    error=str(e),
                )
                db.session.add(failed_raw)
                db.session.commit()
            except:
                pass
        return jsonify({"error": str(e)}), 500
