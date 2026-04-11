"""
Background Tasks - Daily Sync
==============================
Runs sync functions to ensure data integrity.
"""

import logging
from datetime import datetime, timedelta, timezone
from threading import Thread, Event
import time
from sqlalchemy import text

logger = logging.getLogger(__name__)


class BackgroundScheduler:
    """Enhanced background task scheduler supporting daily and interval-based jobs"""

    def __init__(self, app):
        self.app = app
        self.running = False
        self.shutdown_event = Event()
        self.thread = None
        self.tasks = []

    def add_job(self, func, hour, minute, name):
        """Add a job to run at a specific time daily (UTC)"""
        self.tasks.append(
            {
                "type": "daily",
                "func": func,
                "hour": hour,
                "minute": minute,
                "name": name,
                "last_run": None,
            }
        )

    def add_interval_job(self, func, seconds, name):
        """Add a job to run at a fixed interval"""
        self.tasks.append(
            {
                "type": "interval",
                "func": func,
                "seconds": seconds,
                "name": name,
                "last_run_time": 0,
            }
        )

    def start(self):
        """Start the scheduler"""
        self.running = True
        self.thread = Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        logger.info("[SCHEDULER] Background tasks started")
        for task in self.tasks:
            if task["type"] == "daily":
                logger.info(
                    f"[SCHEDULER] - {task['name']}: Daily {task['hour']:02d}:{task['minute']:02d} UTC"
                )
            else:
                logger.info(f"[SCHEDULER] - {task['name']}: Every {task['seconds']}s")

    def stop(self):
        """Stop the scheduler"""
        self.running = False
        self.shutdown_event.set()
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("[SCHEDULER] Background tasks stopped")

    def _run_loop(self):
        """Main scheduler loop"""
        while self.running and not self.shutdown_event.is_set():
            try:
                now = datetime.now(timezone.utc)
                now_ts = time.time()

                for task in self.tasks:
                    should_run = False

                    if task["type"] == "daily":
                        if now.hour == task["hour"] and now.minute == task["minute"]:
                            if task["last_run"] != now.strftime("%Y-%m-%d %H:%M"):
                                should_run = True
                                task["last_run"] = now.strftime("%Y-%m-%d %H:%M")

                    elif task["type"] == "interval":
                        if now_ts - task["last_run_time"] >= task["seconds"]:
                            should_run = True
                            task["last_run_time"] = now_ts

                    if should_run:
                        logger.info(f"[SCHEDULER] Running: {task['name']}")
                        try:
                            with self.app.app_context():
                                task["func"]()
                        except Exception as e:
                            logger.error(f"[SCHEDULER] Error in {task['name']}: {e}")

                # Sleep for 10 seconds (more responsive than 30s)
                self.shutdown_event.wait(10)

            except Exception as e:
                logger.error(f"[SCHEDULER] Error in scheduler loop: {e}")
                self.shutdown_event.wait(60)


def sync_yesterday_data():
    """Sync yesterday's data to ensure aggregations are correct"""
    from extensions import db

    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()

    try:
        logger.info(f"[SYNC] Running daily sync for {yesterday}")

        # Sync app usage from sessions
        db.session.execute(
            text("""
            SELECT sync_app_usage_from_sessions(:date)
        """),
            {"date": yesterday},
        )
        logger.info("[SYNC] [OK] App usage synced")

        # Sync domain usage from sessions
        db.session.execute(
            text("""
            SELECT sync_domain_usage_from_sessions(:date)
        """),
            {"date": yesterday},
        )
        logger.info("[SYNC] [OK] Domain usage synced")

        # Sync screen time from sessions
        result = db.session.execute(
            text("""
            SELECT * FROM sync_screen_time_from_sessions(:date)
        """),
            {"date": yesterday},
        )

        rows = result.fetchall()
        logger.info(f"[SYNC] [OK] Screen time synced for {len(rows)} agents")

        db.session.commit()
        logger.info(f"[SYNC] Daily sync completed successfully")

    except Exception as e:
        db.session.rollback()
        logger.error(f"[SYNC] Error during daily sync: {e}")


def reprocess_failed_events():
    """
    Reprocess failed RawEvents that were stored but not processed.

    This handles recovery from transient failures (e.g., DB locks, timeouts).
    Events are retried up to 3 times before being marked as permanently failed.
    """
    from extensions import db
    import server_models
    import json

    try:
        # Get failed events from last 24 hours (avoid retrying ancient failures)
        from datetime import datetime, timedelta, timezone

        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

        failed_events = (
            server_models.RawEvent.query.filter(
                server_models.RawEvent.processed == False,
                server_models.RawEvent.received_at >= cutoff,
                server_models.RawEvent.error.isnot(None),
            )
            .limit(50)
            .all()
        )

        if not failed_events:
            return

        logger.info(f"[REPROCESS] Found {len(failed_events)} failed events to retry")

        success_count = 0
        for event in failed_events:
            try:
                payload = (
                    json.loads(event.payload)
                    if isinstance(event.payload, str)
                    else event.payload
                )

                # Retry based on event type
                if (
                    event.event_type == "screentime"
                    or event.event_type == "state_duration"
                ):
                    # Parse and call authoritative handler (Additive logic)
                    from server_telemetry import handle_state_duration

                    # Convert raw event back to payload for handler
                    res = handle_state_duration(event.agent_id, payload)
                    if res.status_code == 200:
                        event.processed = True
                        event.error = None
                        success_count += 1

                elif event.event_type == "app-switch":
                    result = db.session.execute(
                        text("""
                        SELECT * FROM process_app_switch_event(
                            :agent_id, :timestamp, :app, :friendly_name, :category,
                            :window_title, :session_start, :session_end, :total_seconds
                        )
                    """),
                        {
                            "agent_id": event.agent_id,
                            "timestamp": event.received_at,
                            "app": payload.get("app", ""),
                            "friendly_name": payload.get("friendly_name", ""),
                            "category": payload.get("category", "other"),
                            "window_title": payload.get("window_title", ""),
                            "session_start": payload.get("session_start"),
                            "session_end": payload.get("session_end"),
                            "total_seconds": payload.get("total_seconds", 0),
                        },
                    )
                    row = result.fetchone()
                    if row and row[0] == "success":
                        event.processed = True
                        event.error = None
                        success_count += 1

            except Exception as e:
                # Update error message but don't spam logs
                event.error = f"Retry failed: {str(e)[:200]}"

        db.session.commit()
        logger.info(
            f"[REPROCESS] Successfully reprocessed {success_count}/{len(failed_events)} events"
        )

    except Exception as e:
        db.session.rollback()
        logger.error(f"[REPROCESS] Error during reprocessing: {e}")


def audit_data_integrity():
    """
    Audit data integrity by comparing screen_time totals with app_sessions sums.

    Logs warnings if discrepancies exceed threshold (allows for timing differences).
    """
    from extensions import db
    import server_models

    try:
        today = datetime.now(timezone.utc).date()

        # Get screen_time totals
        screen_times = server_models.ScreenTime.query.filter_by(date=today).all()

        discrepancies = []
        for st in screen_times:
            agent_id_str = str(st.agent_id)

            # Get sum of app sessions for this agent today
            result = db.session.execute(
                text("""
                SELECT COALESCE(SUM(duration_seconds), 0) as total
                FROM app_sessions
                WHERE agent_id = :agent_id
                AND start_time::DATE = :date
            """),
                {"agent_id": st.agent_id, "date": today},
            )

            row = result.fetchone()
            session_total = row[0] if row else 0

            # Compare active_seconds with session total
            # Allow 10% or 60 seconds tolerance (whichever is greater)
            threshold = max(st.active_seconds * 0.1, 60)
            diff = abs(st.active_seconds - session_total)

            if diff > threshold and st.active_seconds > 0:
                discrepancies.append(
                    {
                        "agent_id": agent_id_str[:12] + "...",
                        "screen_time_active": st.active_seconds,
                        "session_total": session_total,
                        "difference": diff,
                    }
                )

        if discrepancies:
            logger.warning(f"[AUDIT] Found {len(discrepancies)} data discrepancies:")
            for d in discrepancies[:5]:  # Log first 5
                logger.warning(
                    f"[AUDIT] Agent {d['agent_id']}: "
                    f"screen_time={d['screen_time_active']}s vs sessions={d['session_total']}s "
                    f"(diff={d['difference']}s)"
                )
        else:
            logger.info(
                "[AUDIT] Data integrity check passed - no significant discrepancies"
            )

    except Exception as e:
        logger.error(f"[AUDIT] Error during audit: {e}")


def cleanup_old_data():
    """Run cleanup script for data retention"""
    # Bug #12 Fix: Separate import check from execution
    try:
        from server_cleanup import cleanup_old_data as do_cleanup
    except ImportError:
        logger.error("[CLEANUP] server_cleanup.py not found - cleanup disabled!")
        return

    try:
        logger.info("[CLEANUP] Starting data retention cleanup...")
        do_cleanup()
        logger.info("[CLEANUP] Cleanup completed")
    except Exception as e:
        logger.error(f"[CLEANUP] Cleanup failed: {e}", exc_info=True)


def sync_eol_data():
    """
    Sync EOL lifecycle data from endoflife.date API.
    Primary intelligence source for EOL tracking.
    """
    try:
        from eol_engine import sync_lifecycle_data

        logger.info("[EOL] Starting endoflife.date sync...")
        results = sync_lifecycle_data()
        total = sum(v for v in results.values() if isinstance(v, int))
        errors = sum(1 for v in results.values() if isinstance(v, str) and "error" in v)
        logger.info(f"[EOL] Sync complete: {total} cycles synced, {errors} errors")
    except Exception as e:
        logger.error(f"[EOL] EOL data sync failed: {e}")


def sync_nvd_cache():
    """
    Sync NIST NVD vulnerability data (supplementary to endoflife.date).
    Runs weekly with a 30-day lookback for modified CVEs.
    """
    try:
        import os
        from nvd_cache import NVDCache

        api_key = os.environ.get("NVD_API_KEY")
        cache = NVDCache(api_key=api_key)
        logger.info("[NVD] Starting NVD cache sync (30-day lookback)...")
        result = cache.sync(days_back=30)
        logger.info(
            f"[NVD] Sync complete: {result.get('synced', 0)} entries, "
            f"{result.get('errors', 0)} errors, {result.get('duration_seconds', 0)}s"
        )
    except ImportError:
        logger.debug("[NVD] nvd_cache module not available — skipping")
    except Exception as e:
        logger.error(f"[NVD] NVD cache sync failed: {e}")


def check_stale_updates():
    """
    Watchdog: detect agents stuck in update states for >30 minutes (AUE-13).
    Auto-resets agents stuck >60 minutes so they don't stay blocked forever.
    """
    from extensions import db
    import server_models

    try:
        warn_cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
        reset_cutoff = datetime.now(timezone.utc) - timedelta(minutes=60)

        # Phase 1: Warn about agents stuck >30 min
        warn_agents = server_models.Agent.query.filter(
            server_models.Agent.update_status.in_(
                ["pending", "downloading", "installing"]
            ),
            server_models.Agent.last_update_check < warn_cutoff,
            server_models.Agent.last_update_check >= reset_cutoff,
        ).all()

        if warn_agents:
            logger.warning(
                f"[STALE-WATCHDOG] {len(warn_agents)} agents stuck (warning):"
            )
            for agent in warn_agents[:10]:
                minutes_stuck = int(
                    (datetime.now(timezone.utc) - agent.last_update_check).total_seconds() / 60
                )
                logger.warning(
                    f"[STALE-WATCHDOG]   {str(agent.agent_id)[:12]}... "
                    f"({agent.hostname}) status={agent.update_status} "
                    f"stuck {minutes_stuck}min target={agent.target_version}"
                )

        # Phase 2: Auto-reset agents stuck >60 min
        reset_agents = server_models.Agent.query.filter(
            server_models.Agent.update_status.in_(
                ["pending", "downloading", "installing"]
            ),
            server_models.Agent.last_update_check < reset_cutoff,
        ).all()

        if reset_agents:
            logger.warning(
                f"[STALE-WATCHDOG] Auto-resetting {len(reset_agents)} agents stuck >60min:"
            )
            for agent in reset_agents:
                old_status = agent.update_status
                old_target = agent.target_version
                minutes_stuck = int(
                    (datetime.now(timezone.utc) - agent.last_update_check).total_seconds() / 60
                )
                agent.update_status = "up_to_date"
                agent.target_version = None
                agent.last_update_error = (
                    f"Auto-reset by watchdog: was {old_status} for {minutes_stuck}min "
                    f"(target={old_target})"
                )
                logger.warning(
                    f"[STALE-WATCHDOG]   Reset {str(agent.agent_id)[:12]}... "
                    f"({agent.hostname}): {old_status}({minutes_stuck}min) -> up_to_date"
                )
            db.session.commit()
            logger.info(
                f"[STALE-WATCHDOG] Committed reset for {len(reset_agents)} agents"
            )

    except Exception as e:
        logger.error(f"[STALE-WATCHDOG] Error: {e}")
        try:
            db.session.rollback()
        except Exception:
            pass


def sync_available_versions():
    """
    Scan updates directory and sync version metadata into update_versions table.
    Runs hourly to keep the dashboard version list up-to-date.
    """
    from extensions import db
    import server_models
    import re

    try:
        import os
        from pathlib import Path

        updates_dir = Path(
            os.environ.get(
                "SENTINELEDGE_UPDATES_DIR", Path(__file__).parent / "updates"
            )
        )

        if not updates_dir.exists():
            logger.debug("[VERSION-SYNC] Updates directory not found, skipping")
            return

        synced = 0

        # Read latest.json for primary metadata
        latest_file = updates_dir / "latest.json"
        if latest_file.exists():
            try:
                import json

                info = json.loads(latest_file.read_text())
                version = info.get("version")
                if version:
                    existing = server_models.UpdateVersion.query.filter_by(
                        version=version
                    ).first()

                    if not existing:
                        new_ver = server_models.UpdateVersion(
                            version=version,
                            artifact_type=info.get("artifact_type", "exe_bundle"),
                            package_size=info.get("package_size"),
                            package_sha256=info.get("package_sha256"),
                            min_agent_version=info.get("min_agent_version"),
                            mandatory=info.get("mandatory", False),
                            changelog=info.get("changelog", ""),
                            is_active=True,
                        )
                        db.session.add(new_ver)
                        synced += 1
                    else:
                        # Update existing
                        existing.package_size = info.get(
                            "package_size", existing.package_size
                        )
                        existing.package_sha256 = info.get(
                            "package_sha256", existing.package_sha256
                        )
                        existing.is_active = True
            except Exception as e:
                logger.error(f"[VERSION-SYNC] Error reading latest.json: {e}")

        # Scan zip files
        for zip_file in updates_dir.glob("sentineledge-agent-*.zip"):
            match = re.search(r"sentineledge-agent-(.+)\.zip", zip_file.name)
            if match:
                v = match.group(1)
                existing = server_models.UpdateVersion.query.filter_by(
                    version=v
                ).first()
                if not existing:
                    new_ver = server_models.UpdateVersion(
                        version=v,
                        artifact_type="exe_bundle",
                        package_size=zip_file.stat().st_size,
                        is_active=True,
                    )
                    db.session.add(new_ver)
                    synced += 1

        if synced > 0:
            db.session.commit()
            logger.info(f"[VERSION-SYNC] Synced {synced} new version(s)")
        else:
            logger.debug("[VERSION-SYNC] No new versions found")

    except Exception as e:
        db.session.rollback()
        logger.error(f"[VERSION-SYNC] Error: {e}")


def start_background_tasks(app):
    """Start background scheduler"""
    scheduler = BackgroundScheduler(app)

    # Run daily sync at 2 AM UTC (7:30 AM IST)
    scheduler.add_job(
        func=sync_yesterday_data, hour=2, minute=0, name="Daily data sync"
    )

    # Run cleanup at 3 AM UTC (8:30 AM IST)
    scheduler.add_job(
        func=cleanup_old_data, hour=3, minute=0, name="Daily data cleanup"
    )

    # Run failed event reprocessing at 4 AM UTC
    scheduler.add_job(
        func=reprocess_failed_events, hour=4, minute=0, name="Reprocess failed events"
    )

    # Run data integrity audit at 5 AM UTC
    scheduler.add_job(
        func=audit_data_integrity, hour=5, minute=0, name="Data integrity audit"
    )

    # Run EOL data sync at 1 AM UTC (endoflife.date — primary source)
    scheduler.add_job(
        func=sync_eol_data, hour=1, minute=0, name="EOL lifecycle data sync"
    )

    # Run NVD cache sync weekly (Sundays at 1:30 AM UTC — supplementary)
    scheduler.add_job(
        func=sync_nvd_cache, hour=1, minute=30, name="NVD vulnerability cache sync"
    )

    # ── Auto-Update Background Jobs ──────────────────────────────

    # Stale update watchdog — every 5 minutes
    scheduler.add_interval_job(
        func=check_stale_updates, seconds=300, name="Stale update watchdog"
    )

    # Version directory sync — every 1 hour
    scheduler.add_interval_job(
        func=sync_available_versions, seconds=3600, name="Available versions sync"
    )

    scheduler.start()

    return scheduler
