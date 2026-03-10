#!/usr/bin/env python3
"""
Targeted screentime anomaly repair.

Dry-run:
  python repair_screentime_anomalies.py --dry-run

Apply:
  python repair_screentime_anomalies.py --apply
"""
import argparse
import json
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import text

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server_app import create_app  # noqa: E402
from extensions import db  # noqa: E402


MAX_DAY_SECONDS = 86400
AWAY_THRESHOLD_SECONDS = 7200
SUSPICIOUS_JUMP_SECONDS = 6 * 3600
SUSPICIOUS_AWAY_SECONDS = 4 * 3600
KNOWN_IMPACT_WINDOWS = [
    ("2026-02-20", "2026-02-24"),  # lock/suspend/resume anomaly window from helper timeline
]


def detect_anomalies(conn):
    window_bounds = [
        (datetime.strptime(start, "%Y-%m-%d").date(), datetime.strptime(end, "%Y-%m-%d").date())
        for start, end in KNOWN_IMPACT_WINDOWS
    ]

    def in_known_window(day_value: date) -> bool:
        return any(start <= day_value <= end for start, end in window_bounds)

    rows = conn.execute(text("""
        SELECT
            st.agent_id::text AS agent_id,
            st.date AS date,
            st.active_seconds,
            st.idle_seconds,
            st.locked_seconds,
            st.away_seconds,
            st.session_start,
            st.last_updated,
            (st.active_seconds + st.idle_seconds + st.locked_seconds + st.away_seconds) AS total_seconds,
            LAG(st.active_seconds + st.idle_seconds + st.locked_seconds + st.away_seconds)
              OVER (PARTITION BY st.agent_id ORDER BY st.date) AS prev_total_seconds,
            LAG(st.session_start)
              OVER (PARTITION BY st.agent_id ORDER BY st.date) AS prev_session_start
        FROM screen_time st
        ORDER BY st.agent_id, st.date
    """), {"max_day": MAX_DAY_SECONDS}).mappings().all()

    anomalies = []
    for row in rows:
        reasons = []
        active = int(row["active_seconds"] or 0)
        idle = int(row["idle_seconds"] or 0)
        locked = int(row["locked_seconds"] or 0)
        away = int(row["away_seconds"] or 0)
        total = int(row["total_seconds"] or 0)
        prev_total = row["prev_total_seconds"]
        prev_total = int(prev_total) if prev_total is not None else None
        day = row["date"]
        session_start = row["session_start"]
        prev_session_start = row["prev_session_start"]

        # Criteria 1: physical/day bounds.
        if any(v < 0 or v > MAX_DAY_SECONDS for v in (active, idle, locked, away)) or total > MAX_DAY_SECONDS:
            reasons.append("physical_limit_violation")

        # Criteria 2: suspicious single-day jumps tied to session churn.
        if prev_total is not None:
            delta = total - prev_total
            session_changed = session_start != prev_session_start
            if delta > SUSPICIOUS_JUMP_SECONDS and (session_changed or away >= SUSPICIOUS_AWAY_SECONDS):
                reasons.append(f"suspicious_jump(delta={delta},session_changed={session_changed})")

        # Criteria 3: known impacted windows from helper logs.
        if in_known_window(day) and away >= SUSPICIOUS_AWAY_SECONDS:
            reasons.append("known_window_away_spike")

        if reasons:
            row_dict = dict(row)
            row_dict["anomaly_reasons"] = reasons
            anomalies.append(row_dict)

    return anomalies


def recompute_from_spans(conn, agent_id, day):
    spans = conn.execute(text("""
        SELECT state, SUM(duration_seconds)::int AS sec
        FROM screen_time_spans
        WHERE agent_id::text = :agent_id
          AND DATE(start_time) = :day
        GROUP BY state
    """), {"agent_id": agent_id, "day": day}).mappings().all()

    if not spans:
        return None

    totals = {"active_seconds": 0, "idle_seconds": 0, "locked_seconds": 0, "away_seconds": 0}
    for row in spans:
        state = (row["state"] or "").lower()
        sec = int(row["sec"] or 0)
        if state == "active":
            totals["active_seconds"] = sec
        elif state == "idle":
            totals["idle_seconds"] = sec
        elif state == "locked":
            # Conservative split: long locked spans are away.
            if sec >= AWAY_THRESHOLD_SECONDS:
                totals["away_seconds"] += sec
            else:
                totals["locked_seconds"] += sec

    total = sum(totals.values())
    if total > MAX_DAY_SECONDS:
        scale = MAX_DAY_SECONDS / total
        for k in totals:
            totals[k] = int(totals[k] * scale)
    return totals


def recompute_from_raw_screentime(conn, agent_id, day):
    rows = conn.execute(text("""
        SELECT payload
        FROM raw_events
        WHERE agent_id::text = :agent_id
          AND event_type = 'screentime'
          AND DATE(received_at) = :day
    """), {"agent_id": agent_id, "day": day}).mappings().all()

    if not rows:
        return None

    best = {"active_seconds": 0, "idle_seconds": 0, "locked_seconds": 0, "away_seconds": 0}
    for row in rows:
        try:
            payload = json.loads(row["payload"] or "{}")
            best["active_seconds"] = max(best["active_seconds"], int(payload.get("active_seconds", 0) or 0))
            best["idle_seconds"] = max(best["idle_seconds"], int(payload.get("idle_seconds", 0) or 0))
            best["locked_seconds"] = max(best["locked_seconds"], int(payload.get("locked_seconds", 0) or 0))
            best["away_seconds"] = max(best["away_seconds"], int(payload.get("away_seconds", 0) or 0))
        except Exception:
            continue

    total = sum(best.values())
    if total > MAX_DAY_SECONDS:
        scale = MAX_DAY_SECONDS / total
        for k in best:
            best[k] = int(best[k] * scale)
    return best


def ensure_audit_table(conn):
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS screen_time_repair_audit (
            id SERIAL PRIMARY KEY,
            agent_id UUID NOT NULL,
            date DATE NOT NULL,
            old_values JSONB NOT NULL,
            new_values JSONB NOT NULL,
            reason TEXT NOT NULL,
            repaired_at TIMESTAMP NOT NULL DEFAULT NOW()
        );
    """))


def apply_repairs(conn, repair_rows):
    ensure_audit_table(conn)
    for row in repair_rows:
        conn.execute(text("""
            UPDATE screen_time
            SET active_seconds = :active,
                idle_seconds = :idle,
                locked_seconds = :locked,
                away_seconds = :away,
                last_updated = NOW()
            WHERE agent_id::text = :agent_id
              AND date = :day
        """), {
            "agent_id": row["agent_id"],
            "day": row["date"],
            "active": row["new"]["active_seconds"],
            "idle": row["new"]["idle_seconds"],
            "locked": row["new"]["locked_seconds"],
            "away": row["new"]["away_seconds"],
        })
        conn.execute(text("""
            INSERT INTO screen_time_repair_audit(agent_id, date, old_values, new_values, reason)
            VALUES (CAST(:agent_id AS UUID), :day, CAST(:old_values AS jsonb), CAST(:new_values AS jsonb), :reason)
        """), {
            "agent_id": row["agent_id"],
            "day": row["date"],
            "old_values": json.dumps(row["old"]),
            "new_values": json.dumps(row["new"]),
            "reason": row["reason"],
        })


def main():
    parser = argparse.ArgumentParser(description="Repair anomalous screen_time rows")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        conn = db.session.connection()
        anomalies = detect_anomalies(conn)
        repairs = []

        for row in anomalies:
            agent_id = row["agent_id"]
            day = row["date"]

            old = {
                "active_seconds": int(row["active_seconds"] or 0),
                "idle_seconds": int(row["idle_seconds"] or 0),
                "locked_seconds": int(row["locked_seconds"] or 0),
                "away_seconds": int(row["away_seconds"] or 0),
            }

            new_totals = recompute_from_spans(conn, agent_id, day)
            reason = "recomputed_from_spans"
            if not new_totals:
                new_totals = recompute_from_raw_screentime(conn, agent_id, day)
                reason = "recomputed_from_raw_screentime"
            if not new_totals:
                continue

            reason = f"{reason}; detected={','.join(row.get('anomaly_reasons', []))}"

            repairs.append({
                "agent_id": agent_id,
                "date": str(day),
                "old": old,
                "new": new_totals,
                "reason": reason,
            })

        print(json.dumps({
            "mode": "dry-run" if args.dry_run else "apply",
            "anomalies_detected": len(anomalies),
            "repair_candidates": len(repairs),
            "repairs": repairs[:200],  # keep output bounded
        }, indent=2))

        if args.apply:
            apply_repairs(conn, repairs)
            db.session.commit()
            print(f"Applied {len(repairs)} repairs.")


if __name__ == "__main__":
    main()
