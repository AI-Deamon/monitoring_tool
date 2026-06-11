"""
Data Collector Module - ENHANCED
================================
Orchestrates all data collection and builds heartbeat packets.
Now includes session-based domain tracking integrated with app/idle tracking.
"""

import json
import math
from datetime import datetime, timezone, timedelta

# IST Timezone for Asia/Kolkata
IST = timezone(timedelta(hours=5, minutes=30))
from pathlib import Path
from typing import Dict, List, Optional
import logging
import time

from .idle import IdleDetector
from .window import WindowTracker
from .domain import ActiveDomainTracker, BrowserHistoryTracker
from .inventory import InventoryTracker
from .hardware_collector import HardwareCollector
from .eol_collector import EOLCollector
from .config import HelperConfig


logger = logging.getLogger(__name__)


def validate_duration(value, default=0, max_value=86400, context="duration"):
    """Validate duration is a sane number (0-24 hours)."""
    try:
        val = float(value)
        if not (0 <= val <= max_value):
            logger.error(
                f"[VALIDATION] {context} out of range: {val}s, using {default}s"
            )
            return default
        if math.isnan(val) or math.isinf(val):
            logger.error(f"[VALIDATION] {context} is NaN/Inf: {val}, using {default}s")
            return default
        return val
    except (ValueError, TypeError):
        logger.error(f"[VALIDATION] {context} non-numeric: {value}, using {default}s")
        return default


class DataCollector:
    """
    Orchestrates data collection from all modules including domain sessions.

    ENHANCED:
    - Uses enhanced IdleDetector with sub-second precision
    - Uses enhanced WindowTracker with session persistence
    - Includes cumulative screen time tracking
    - Supports session recovery after restarts
    """

    def __init__(self, config: HelperConfig, buffer_db=None):
        self.config = config
        self.state_detector = None  # Link set by main.py
        self.buffer_db = buffer_db

        try:
            # Initialize enhanced modules
            logger.info("[INIT] Starting DataCollector initialization...")

            self.idle_detector = IdleDetector(
                config.idle_threshold,
                enable_app_specific_thresholds=config.enable_app_specific_thresholds,
                on_idle_complete=self.send_idle_event,
            )
            logger.info("[INIT] [OK] IdleDetector")

            self.window_tracker = WindowTracker(
                capture_titles=config.capture_window_titles,
                state_file=config.data_dir / "window_state.json",
            )
            logger.info("[INIT] [OK] WindowTracker")

            # Domain tracking - NEW: Active domain tracker for sessions
            self.active_domain_tracker = ActiveDomainTracker(config.capture_full_urls)
            logger.info("[INIT] [OK] ActiveDomainTracker")

            # Legacy history tracker (for backward compatibility)
            self.history_tracker = BrowserHistoryTracker(config.capture_full_urls)
            logger.info("[INIT] [OK] BrowserHistoryTracker")

            self.inventory_tracker = InventoryTracker(config)
            logger.info("[INIT] [OK] InventoryTracker")

            self.hardware_collector = HardwareCollector(config)
            logger.info("[INIT] [OK] HardwareCollector")

            self.eol_collector = EOLCollector(config)
            logger.info("[INIT] [OK] EOLCollector")

            # State
            self.sequence_number = 0
            self.last_inventory_time = None
            # Domain session state
            self._last_idle_state = "active"
            self._last_foreground_app = None

            # Enhanced: Session tracking
            self._session_start = datetime.now(IST)
            self._heartbeat_count = 0

            # Track current date for midnight detection
            self._current_date = datetime.now(IST).date()

            self.window_tracking_failures = 0
            logger.info("[INIT] [OK] Initialization complete")

            # Load persisted state
            logger.info("[INIT] Loading persisted state...")
            self._load_state()
            logger.info("[INIT] [OK] State loaded")

            # Apply initial config
            logger.info("[INIT] Applying config...")
            self.apply_config()
            logger.info("[INIT] [OK] Config applied")

            logger.info(
                "[COLLECTOR] Enhanced DataCollector initialized with session tracking"
            )

        except Exception as e:
            logger.error("=" * 60)
            logger.error("[INIT] FATAL ERROR during DataCollector initialization!")
            logger.error(f"[INIT] Error type: {type(e).__name__}")
            logger.error(f"[INIT] Error message: {str(e)}")
            logger.error("=" * 60)
            import traceback

            logger.error(traceback.format_exc())
            logger.error("=" * 60)
            raise  # Re-raise to crash properly with full error

    def apply_config(self):
        """Apply configuration changes to sub-modules"""
        self.idle_detector.update_settings(
            self.config.idle_threshold,
            enable_app_specific_thresholds=self.config.enable_app_specific_thresholds,
        )
        self.window_tracker.update_settings(self.config.capture_window_titles)
        self.active_domain_tracker.update_settings(self.config.capture_full_urls)
        self.history_tracker.update_settings(self.config.capture_full_urls)

    def _load_state(self):
        """Load persisted state"""
        try:
            if self.config.state_file.exists():
                with open(self.config.state_file, "r") as f:
                    state = json.load(f)
                    self.sequence_number = state.get("sequence_number", 0)
                    self.last_inventory_time = state.get("last_inventory_time")

                    # Restore domain tracker states
                    if "active_domain_state" in state:
                        self.active_domain_tracker.set_state(
                            state["active_domain_state"]
                        )
                    if "history_state" in state:
                        self.history_tracker.set_state(state["history_state"])
                    # Legacy compatibility
                    elif "domain_state" in state:
                        self.history_tracker.set_state(state["domain_state"])

        except Exception as e:
            logger.warning(f"Failed to load state: {e}")

    def _save_state(self):
        """Save state to disk"""
        try:
            state = {
                "sequence_number": self.sequence_number,
                "last_inventory_time": self.last_inventory_time,
                "active_domain_state": self.active_domain_tracker.get_state(),
                "history_state": self.history_tracker.get_state(),
            }

            # Atomic write
            temp_file = self.config.state_file.with_suffix(".tmp")
            with open(temp_file, "w") as f:
                json.dump(state, f, indent=2)
            temp_file.replace(self.config.state_file)

        except Exception as e:
            logger.error(f"Failed to save state: {e}")

    def get_system_state(self) -> str:
        """Standardized FIX 3: Force locked state reporting"""
        if self.state_detector and self.state_detector.is_locked:
            return "locked"

        if self.state_detector:
            return self.state_detector.current_state

        return "active"

    def collect_heartbeat(self) -> Dict:
        """
        Collect data for a heartbeat packet with enhanced screen time tracking.

        ENHANCED:
        - Includes cumulative screen time counters from IdleDetector
        - Includes accurate app session duration from WindowTracker
        - Supports session recovery after restarts

        Returns:
            Heartbeat dict ready to send to core
        """
        now = datetime.now(IST)
        self.sequence_number += 1
        self._heartbeat_count += 1

        # Check for midnight crossing (new day)
        current_date = now.date()
        if current_date != self._current_date:
            logger.info(
                f"[COLLECTOR] Day changed (UTC): {self._current_date} -> {current_date}"
            )

            # NOTE: Do NOT reset state machine counters here.
            # The state machine's own check_daily_boundary() handles
            # midnight resets using LOCAL time (not UTC).
            # Resetting here caused triple-reset bugs (see PLAN-screentime-reset.md).

            # Update current date
            self._current_date = current_date
            self._session_start = now
            self._heartbeat_count = 0

            logger.info("[COLLECTOR] Day changed, counters managed by state machine")

            # FIX: Reset WindowTracker timestamp to prevent overnight duration overflow
            if self.window_tracker:
                logger.info("[COLLECTOR] Resetting WindowTracker for new day...")
                # Reset start time to NOW (prevents overnight overflow)
                self.window_tracker._app_start = now
                logger.info("[COLLECTOR] WindowTracker timestamp reset")

        # ====================================================================
        # STEP 1: Sample foreground window FIRST (needed for lock fallback)
        # ====================================================================
        window_change = None
        current_app = {
            "app_name": "unknown",
            "window_title": None,
            "duration_seconds": 0,
        }

        if self.config.enable_app_tracking:
            # Always sample window to detect lock screen apps (lockapp.exe)
            window_change = self.window_tracker.sample()
            current_app = self.window_tracker.get_current_app_duration()

        # STEP 1.5: Feed foreground app to state detector BEFORE state check
        # This enables lock detection via LOCK_APPS (lockapp.exe, logonui.exe)
        if self.state_detector:
            foreground_app = current_app.get("app_name", "")
            self.state_detector.set_foreground_app(foreground_app)
            self.state_detector._update_state()

        # ====================================================================
        # STEP 2: Get current authoritative state (with defensive guard)
        # ====================================================================
        current_state = self.get_system_state()

        idle_state = {
            "state": current_state,
            "changed": current_state != self._last_idle_state,
            "duration_seconds": 0,  # Timing is now event-driven
        }

        # STEP 3: Re-evaluate app tracking based on idle state
        # ====================================================================
        if self.config.enable_app_tracking:
            is_idle = current_state in ["idle", "locked"]

            if is_idle:
                # User is IDLE/LOCKED - pause app tracking, clear current app
                current_app = {
                    "app_name": None,
                    "window_title": None,
                    "duration_seconds": 0,
                    "is_paused": True,  # Flag to indicate tracking is paused
                }
            else:
                # User is ACTIVE - check window tracking health
                # Check if window tracking is failing
                if current_app.get("app_name") in ["unknown", None, ""]:
                    self.window_tracking_failures += 1
                    if self.window_tracking_failures >= 5:
                        logger.debug(
                            f"[COLLECTOR] Window tracking unavailable ({self.window_tracking_failures} failures)"
                        )
                else:
                    # Window tracking is working
                    if self.window_tracking_failures > 0:
                        logger.info("[COLLECTOR] Window tracking recovered")
                    self.window_tracking_failures = 0

        # ====================================================================
        # NEW: Domain session tracking integrated with heartbeat
        # ====================================================================
        if self.config.enable_domains:
            current_idle = idle_state["state"]
            is_idle = current_idle in ["idle", "locked"]

            # Handle idle state transitions for domain sessions
            if self._last_idle_state != "idle" and current_idle == "idle":
                # User became idle - end domain session
                self.active_domain_tracker.end_session_for_sleep()
            elif self._last_idle_state != "locked" and current_idle == "locked":
                # Workstation locked - end domain session
                self.active_domain_tracker.end_session_for_lock()

            # Sample domain (handles browser detection internally)
            foreground_app = current_app.get("app_name")
            window_title = current_app.get("window_title")

            self.active_domain_tracker.sample(
                foreground_app=foreground_app,
                window_title=window_title,
                is_idle=is_idle,
            )

            # Track state for next cycle
            self._last_idle_state = current_idle
            self._last_foreground_app = foreground_app

        # ====================================================================
        # End domain session tracking
        # ====================================================================

        # ✅ PHASE 2: Screen time deltas now come from StateDetector (which uses state machine)
        # No manual calculation needed here

        # Build simplified heartbeat packet
        heartbeat = {
            "agent_id": self.config.agent_id,
            "username": self.config.username,
            "sequence": self.sequence_number,
            "timestamp": now.isoformat(),
            "pulsetime": self.config.heartbeat_interval,
            "idempotency_key": f"{self.config.agent_id}_{self.sequence_number}",
            # Simple state info for live display
            "system_state": current_state,
            # Enhanced Foreground app info
            "app": {
                "current": current_app["app_name"],
                "friendly_name": current_app.get(
                    "friendly_name", current_app["app_name"]
                ),
                "current_title": current_app.get("window_title"),
                "is_browser": current_app.get("is_browser", False),
            },
            # Enhanced screentime info with deltas for Core aggregation
            "screentime": {
                "session_start": self._session_start.isoformat(),
                "heartbeat_count": self._heartbeat_count,
            },
        }

        # Get cumulative totals from StateDetector (ONLY source of truth)
        # StateDetector calls state_machine.tick() then state_machine.get_daily_totals()
        if self.state_detector:
            # Check if we have final totals from midnight boundary (yesterday's final data)
            final_totals = self.state_detector._final_totals_for_upload
            if final_totals:
                # Use yesterday's final totals instead of current (for proper day storage)
                totals = final_totals
                # Clear the flag after use
                self.state_detector._final_totals_for_upload = None
                final_day = getattr(
                    self.state_detector, "_final_totals_day_for_upload", None
                )
                self.state_detector._final_totals_day_for_upload = None
                # Mark as final data so server stores in yesterday's date
                heartbeat["screentime"]["is_final_day"] = True
                if final_day:
                    heartbeat["screentime"]["final_day_date"] = str(final_day)
                # Persist cleared flags so restart cannot re-send stale final-day data.
                try:
                    self.state_detector._persist_current_state()
                except Exception:
                    pass
            else:
                totals = self.state_detector.get_cumulative_totals()

            heartbeat["screentime"]["active_seconds"] = int(
                totals.get("active_seconds", 0)
            )
            heartbeat["screentime"]["idle_seconds"] = int(totals.get("idle_seconds", 0))
            heartbeat["screentime"]["locked_seconds"] = int(
                totals.get("locked_seconds", 0)
            )
            heartbeat["screentime"]["away_seconds"] = int(totals.get("away_seconds", 0))

        # Add app change info if occurred
        if window_change and window_change.get("changed"):
            heartbeat["app"]["changed"] = True
            heartbeat["app"]["previous"] = window_change.get("app_name")
            heartbeat["app"]["previous_duration"] = validate_duration(
                window_change.get("duration_seconds", 0),
                context=f"previous_duration[{window_change.get('app_name')}]",
            )

        # Add current domain session info (for debugging/display)
        domain_info = self.active_domain_tracker.get_current_session_info()
        if domain_info:
            heartbeat["domain"] = domain_info

        # Track state for next cycle
        self._last_idle_state = current_state
        self._last_foreground_app = current_app.get("app_name")

        # Store collected data in BufferDB for upload
        if self.buffer_db:
            try:
                # Store merged events (app switches, state changes) - from heartbeat
                # Note: The heartbeat contains current app info, but we need to extract events from state detector
                # For now, we'll store what we have in the heartbeat as a merged event
                # In a more complete implementation, we'd collect state spans and domain sessions separately
                pass  # Will implement after checking what data we actually have to store
            except Exception as e:
                logger.error(f"[BUFFER] Error storing data in BufferDB: {e}")

        return heartbeat

    def collect_state_spans(self) -> List[Dict]:
        """
        Collect completed state spans from StateDetector.

        Returns:
            List of span dicts with start, end, duration, state
        """
        if not self.state_detector:
            return []

        try:
            spans = self.state_detector.get_pending_spans()
            if spans:
                logger.info(f"[COLLECTOR] Collected {len(spans)} state spans")
                # Store state spans in BufferDB for upload
                if self.buffer_db:
                    for span in spans:
                        try:
                            self.buffer_db.store_state_span(span)
                        except Exception as e:
                            logger.error(f"[BUFFER] Failed to store state span: {e}")
            return spans
        except Exception as e:
            logger.error(f"State span collection error: {e}")
            return []

    def send_idle_event(self, duration: float):
        """
        Notify core of a completed idle session.
        Accepts clean durations calculated via monotonic clock.
        """
        payload = {
            "type": "idle_event",
            "agent_id": self.config.agent_id,
            "state": "idle",
            "duration_seconds": round(duration, 1),
            "timestamp": datetime.now(IST).isoformat(),
        }

        logger.info(f"[COLLECTOR] Dispatching clean idle event: {duration:.1f}s")
        # In a real implementation, this would queue for upload.
        # For now, we'll store it in a way the core can pick it up.
        # Or if there's a direct upload method, we'd call it.
        # Assuming DataCollector is responsible for 'emitting' which main.py handles.
        if hasattr(self, "_idle_events"):
            self._idle_events.append(payload)
        else:
            self._idle_events = [payload]

    def collect_domain_sessions(self) -> List[Dict]:
        """
        Collect completed domain usage sessions.

        NEW: Returns session-based domain usage data with accurate durations.

        Returns:
            List of domain session dicts with start, end, duration
        """
        if not self.config.enable_domains:
            return []

        try:
            sessions = self.active_domain_tracker.get_pending_sessions()
            if sessions:
                logger.debug(f"[COLLECTOR] Collected {len(sessions)} domain sessions")
                # Store domain sessions in BufferDB for upload
                if self.buffer_db:
                    for session in sessions:
                        try:
                            self.buffer_db.store_domain_sessions(
                                [session]
                            )  # store_domain_sessions expects a list
                        except Exception as e:
                            logger.error(
                                f"[BUFFER] Failed to store domain session: {e}"
                            )
                self._save_state()
            return sessions
        except Exception as e:
            logger.error(f"Domain session collection error: {e}")
            return []

    def collect_browser_history(self) -> List[Dict]:
        """
        Collect browser history domain visits for "Sites Opened" column.

        PURPOSE: Dashboard Column B - "Sites Opened Today"
        - Background tabs you never looked at
        - Quick visits (opened and closed fast)
        - Links opened from emails/docs
        - No duration tracking (just timestamps)

        This is different from active domain tracking (Column A).

        Returns:
            List of domain visit dicts from browser history
        """
        if not self.config.enable_domains:
            return []

        try:
            visits = self.history_tracker.sample()
            self._save_state()
            return visits
        except Exception as e:
            logger.error(f"Browser history collection error: {e}")
            return []

    # Keep legacy alias for backward compatibility
    collect_domains = collect_browser_history

    def collect_inventory(self, force: bool = False) -> Optional[Dict]:
        """
        Collect application inventory.

        The InventoryTracker now handles:
        - 4-hour interval checks internally
        - Hash-based change detection
        - Full inventory on registration (force=True)
        - Only returns data when changes detected

        Args:
            force: Force full inventory (use on registration)

        Returns:
            Inventory dict or None if no changes/not time yet
        """
        if not self.config.enable_inventory and not force:
            return None

        try:
            # Use the new collect() method which handles everything
            inventory = self.inventory_tracker.collect(force=force)

            if inventory:
                # Add agent_id to the result
                inventory["agent_id"] = self.config.agent_id

                # Store inventory in BufferDB for upload
                if self.buffer_db:
                    try:
                        self.buffer_db.store_inventory(inventory)
                    except Exception as e:
                        logger.error(f"[BUFFER] Failed to store inventory: {e}")

                self.last_inventory_time = datetime.now(IST).isoformat()
                self._save_state()

                return inventory

            return None

        except Exception as e:
            logger.error(f"Inventory collection error: {e}")
            return None

    def collect_hardware(self, force: bool = False) -> Optional[Dict]:
        """
        Collect hardware/asset information.

        Args:
            force: Force full collection (use on registration)

        Returns:
            Hardware dict or None if no changes
        """
        try:
            hardware = self.hardware_collector.collect(force=force)

            if hardware:
                hardware["agent_id"] = self.config.agent_id
                return hardware

            return None

        except Exception as e:
            logger.error(f"Hardware collection error: {e}")
            return None
    
    def check_network_changed(self) -> bool:
        """
        Check if network adapters have changed since last collection.

        Returns:
            True if network has changed, False otherwise
        """
        try:
            return self.hardware_collector.check_network_changed()
        except Exception as e:
            logger.error(f"Network change check error: {e}")
            return False
    
    def collect_network_partial(self) -> Optional[Dict]:
        """
        Collect and send ONLY network data when change is detected.
        This is lightweight and called on network events.

        Returns:
            Network-only dict or None if no changes
        """
        try:
            network_data = self.hardware_collector.collect_network_partial()
            if network_data:
                network_data["agent_id"] = self.config.agent_id
                return network_data
            return None
        except Exception as e:
            logger.error(f"Network partial collection error: {e}")
            return None
    
    def get_app_usage_summary(self) -> List[Dict]:
        """[DEPRECATED] Cumulative tracking removed."""
        return []

    def collect_eol_data(self, force: bool = False) -> Optional[Dict]:
        """
        Collect EOL-specific data (update history, ESU, metering, keys, warranty).

        Runs on a 24-hour interval (same cadence as hardware collection).
        Returns None if not due yet and force is False.
        """
        if not force:
            # Piggyback on hardware collector's 24h interval check
            if self.hardware_collector and not self.hardware_collector.should_collect():
                return None

        try:
            eol_data = self.eol_collector.collect_all()
            if eol_data:
                eol_data["agent_id"] = self.config.agent_id
                logger.info("[COLLECTOR] EOL data collected successfully")
                return eol_data
            return None
        except Exception as e:
            logger.error(f"EOL data collection error: {e}")
            return None

    def collect_extended_inventory(self, force: bool = False) -> Optional[Dict]:
        """
        Collect extended inventory (CLI tools, drivers, extensions, plugins, portable apps).

        Uses lazy initialization to avoid importing ExtendedInventoryCollector
        until needed. Runs on a 6-hour interval.

        Args:
            force: Force immediate collection (use on startup)

        Returns:
            Extended inventory dict or None if not due yet
        """
        try:
            # Lazy init
            if not hasattr(self, "_ext_collector"):
                from helper.extended_inventory import ExtendedInventoryCollector

                self._ext_collector = ExtendedInventoryCollector(config=self.config)
                self._ext_last_collect = 0
                logger.info("[COLLECTOR] ExtendedInventoryCollector initialized")

            # 6-hour interval check
            EXT_INTERVAL = 6 * 60 * 60
            now = time.time()
            if not force and (now - self._ext_last_collect < EXT_INTERVAL):
                return None

            logger.info("[COLLECTOR] Starting extended inventory collection...")
            data = self._ext_collector.collect_all()

            if data:
                data["agent_id"] = self.config.agent_id
                self._ext_last_collect = now
                counts = {k: len(v) for k, v in data.items() if isinstance(v, list)}
                logger.info(f"[COLLECTOR] Extended inventory collected: {counts}")
                return data

            return None

        except ImportError as e:
            logger.warning(f"[COLLECTOR] ExtendedInventoryCollector not available: {e}")
            return None
        except Exception as e:
            logger.error(f"[COLLECTOR] Extended inventory collection error: {e}")
            return None

    def collect_security_indicators(
        self, force: bool = False, ext_data: Optional[Dict] = None
    ) -> Optional[Dict]:
        """
        Collect security indicators by analyzing existing data.

        Uses lazy initialization. Interval is config-driven (default: 6 hours).

        Args:
            force: Force immediate collection (use on startup)
            ext_data: Extended inventory data to analyze. If None, only file checks run.

        Returns:
            Security indicators dict or None if not due yet
        """
        try:
            if not getattr(self.config, "enable_security_collection", True):
                return None

            # Lazy init
            if not hasattr(self, "_sec_collector"):
                from helper.security_collector import SecurityCollector

                self._sec_collector = SecurityCollector(config=self.config)
                self._sec_last_collect = 0
                logger.info("[COLLECTOR] SecurityCollector initialized")

            # Configurable security collection interval (default 6h).
            SEC_INTERVAL = int(
                getattr(self.config, "security_collection_interval_seconds", 21600)
            )
            SEC_INTERVAL = max(600, SEC_INTERVAL)
            now = time.time()
            if not force and (now - self._sec_last_collect < SEC_INTERVAL):
                return None

            logger.info("[COLLECTOR] Starting security analysis...")
            data = self._sec_collector.collect_all_security(ext_inventory=ext_data)

            if data:
                data["agent_id"] = self.config.agent_id
                self._sec_last_collect = now
                summary = data.get("summary", {})
                total = len(data.get("indicators", []))
                # DEBUG LOG - MAY BE REMOVED
                logger.info(
                    f"[COLLECTOR] Security indicators READY for communication pipeline ({total} total)"
                )
                logger.info(f"[COLLECTOR] Security breakdown: {summary}")
                return data

            return None

        except ImportError as e:
            logger.warning(f"[COLLECTOR] SecurityCollector not available: {e}")
            return None
        except Exception as e:
            logger.error(f"[COLLECTOR] Security collection error: {e}")
            return None

    def collect_system_visibility(self, force: bool = False) -> Optional[Dict]:
        """
        Collect raw system visibility snapshot (ports/connections/startup/tasks/disk).

        Uses SecurityCollector as a data source, but without risk filtering.
        Interval is config-driven (default: 6 hours).
        """
        try:
            if not getattr(self.config, "enable_system_visibility_collection", True):
                return None

            if not hasattr(self, "_sec_collector"):
                from helper.security_collector import SecurityCollector

                self._sec_collector = SecurityCollector(config=self.config)
                self._sec_last_collect = 0
                logger.info("[COLLECTOR] SecurityCollector initialized")

            if not hasattr(self, "_vis_last_collect"):
                self._vis_last_collect = 0

            vis_interval = int(
                getattr(self.config, "system_visibility_interval_seconds", 1800)
            )
            vis_interval = max(600, vis_interval)
            now = time.time()
            if not force and (now - self._vis_last_collect < vis_interval):
                return None

            logger.info("[COLLECTOR] Starting raw system visibility collection...")
            snapshot = self._sec_collector.collect_system_visibility_snapshot()
            if snapshot:
                snapshot["agent_id"] = self.config.agent_id
                self._vis_last_collect = now
                counts = snapshot.get("counts", {})
                logger.info(f"[COLLECTOR] System visibility collected: {counts}")
                return snapshot

            return None

        except ImportError as e:
            logger.warning(
                f"[COLLECTOR] SecurityCollector not available for visibility: {e}"
            )
            return None
        except Exception as e:
            logger.error(f"[COLLECTOR] System visibility collection error: {e}")
            return None

    def shutdown(self):
        """
        Clean shutdown - end any active sessions.
        Called when helper is stopping.
        """
        logger.info("[COLLECTOR] Shutdown - ending active sessions...")

        # End domain session
        if self.config.enable_domains:
            self.active_domain_tracker.end_session_for_shutdown()

        # Save final state
        self._save_state()

        logger.info("[COLLECTOR] Shutdown complete")
