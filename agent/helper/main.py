"""
SentinelEdge Helper - Enhanced User Session Monitor
Lightweight per-user process that collects telemetry
Handles sleep/wake cycles and restarts gracefully
"""

import sys
import time
import logging
from datetime import datetime, timezone
from pathlib import Path
from threading import Thread, Event

# Add agent directory to path so 'from helper.xxx' imports work correctly
# Path(__file__).parent = agent/helper/
# Path(__file__).parent.parent = agent/
sys.path.insert(0, str(Path(__file__).parent.parent))

from helper.config import HelperConfig
from helper.collector import DataCollector
from helper.comm import CoreCommunicator
from helper.identity_sync import IdentitySynchronizer
from helper.state_detector import StateDetector, SystemState
from helper.performance import (
    get_cpu_throttler,
    get_memory_enforcer,
    init_performance_monitoring,
)
from core.buffer import BufferDB


class SentinelHelper:
    """Main helper process with enhanced resilience"""

    def __init__(self):
        # Load configuration
        self.config = HelperConfig()

        # Setup logging
        self._setup_logging()

        # Initialize components
        self.buffer = BufferDB(self.config.state_dir / "buffer.db")
        self.collector = DataCollector(self.config, buffer_db=self.buffer)
        self.communicator = CoreCommunicator(self.config)
        self.identity_sync = IdentitySynchronizer(self.config)

        # Runtime state
        self.running = False
        self.shutdown_event = Event()
        self.heartbeat_counter = 0
        self.domain_counter = 0
        self.startup_time = datetime.now(timezone.utc)
        self.last_activity_time = self.startup_time

        # Watchdog for detecting stuck main loop
        self._watchdog_counter = 0
        self._last_watchdog_check = 0
        self._stuck_count = 0  # Consecutive stuck detections for self-heal

        # Connection state
        self.core_connected = False
        self.connection_retry_count = 0

        # State detector for reliable lock/unlock detection
        self.state_detector = StateDetector(
            idle_threshold_seconds=self.config.idle_threshold,
            on_state_change=self._on_state_change,
            agent_id=self.config.agent_id,
            data_dir=self.config.state_dir,
        )
        self.system_state = SystemState.ACTIVE

        # Link components for state arbitration
        self.state_detector.idle_detector = self.collector.idle_detector
        self.collector.idle_detector.authority = self.state_detector.authority
        self.collector.state_detector = self.state_detector
        self.state_detector.collector = self.collector  # Link for event emission

        # Wire suspend checker so inventory can abort during sleep
        if hasattr(self.collector, "inventory_tracker"):
            self.collector.inventory_tracker._is_suspended_check = (
                self.state_detector.is_suspended
            )

        self.logger.info("=" * 60)
        self.logger.info("SentinelEdge Helper v2.0 - Enhanced")
        self.logger.info(f"Agent ID: {self.communicator.agent_id}")
        self.logger.info(f"Core URL: {self.config.core_url}")
        self.logger.info(f"Heartbeat Interval: {self.config.heartbeat_interval}s")
        self.logger.info(
            f"Security Collection: enabled={self.config.enable_security_collection}, "
            f"interval={self.config.security_collection_interval_seconds}s"
        )
        self.logger.info(
            f"System Visibility: enabled={self.config.enable_system_visibility_collection}, "
            f"interval={self.config.system_visibility_interval_seconds}s"
        )
        self.logger.info(f"Startup: {self.startup_time.isoformat()}")
        self.logger.info("=" * 60)

        # Register config change callback
        self.config.register_change_callback(self._on_config_change)

    def _on_config_change(self, config: HelperConfig):
        """Handle configuration changes dynamically"""
        self.logger.info("[CONFIG] Configuration changed - applying updates...")
        try:
            # Update collector settings
            self.collector.apply_config()
            self.logger.info("[CONFIG] Collector settings updated")
        except Exception as e:
            self.logger.error(f"Error applying config changes: {e}")

    def _log_diagnostic_state(self, loop_iteration: int, current_interval: int):
        """
        Comprehensive diagnostic logging to catch silent failures.
        Called every 60 iterations (~1-2 minutes) to detect stuck states.
        """
        try:
            diag = []
            diag.append("=" * 60)
            diag.append("[DIAGNOSTIC] Helper State Dump")
            diag.append("=" * 60)

            # 1. Main loop state
            diag.append(f"  Loop Iteration: {loop_iteration}")
            diag.append(f"  Current Interval: {current_interval}s")
            diag.append(f"  Core Connected: {self.core_connected}")
            diag.append(f"  Running: {self.running}")

            # 2. State detector state
            try:
                state_detector_state = self.state_detector.get_state()
                diag.append(f"  State Detector: {state_detector_state.value}")
                diag.append(f"  State Detector Running: {self.state_detector._running}")
                diag.append(
                    f"  Is Locked Flag: {self.state_detector.authority.state == SystemState.LOCKED}"
                )
            except Exception as e:
                diag.append(f"  State Detector: ERROR - {e}")

            # 3. Collector state
            try:
                last_idle = getattr(self.collector, "_last_idle_state", "unknown")
                last_app = getattr(self.collector, "_last_foreground_app", "unknown")
                heartbeat_count = getattr(self.collector, "_heartbeat_count", 0)
                diag.append(f"  Collector Last Idle State: {last_idle}")
                diag.append(f"  Collector Last App: {last_app}")
                diag.append(f"  Collector Heartbeat Count: {heartbeat_count}")
            except Exception as e:
                diag.append(f"  Collector: ERROR - {e}")

            # 4. Idle Detector state
            try:
                # Get idle seconds from StateDetector (single source of truth)
                idle_seconds = self.state_detector._get_idle_seconds()
                current_idle_state = self.state_detector.current_state
                idle_detector_state = (
                    "idle" if self.collector.idle_detector.is_idle() else "active"
                )
                is_locked = self.collector.idle_detector.is_locked
                diag.append(f"  Idle Seconds: {idle_seconds:.1f}s")
                diag.append(f"  System State: {current_idle_state}")
                diag.append(f"  IdleDetector State: {idle_detector_state}")
                diag.append(f"  IdleDetector Locked: {is_locked}")
            except Exception as e:
                diag.append(f"  Idle Detector: ERROR - {e}")

            # 5. Window Tracker state
            try:
                window_tracker = self.collector.window_tracker
                current_app = window_tracker.get_current_app_duration()
                diag.append(
                    f"  Window Tracker App: {current_app.get('app_name', 'unknown')}"
                )
                diag.append(
                    f"  Window Tracker Duration: {current_app.get('duration_seconds', 0)}s"
                )
            except Exception as e:
                diag.append(f"  Window Tracker: ERROR - {e}")

            # 6. Counters
            diag.append(f"  Heartbeats Sent: {self.heartbeat_counter}")
            diag.append(f"  Domains Sent: {self.domain_counter}")
            diag.append(f"  Connection Retries: {self.connection_retry_count}")

            # 7. Uptime
            uptime = (datetime.now(timezone.utc) - self.startup_time).total_seconds()
            diag.append(
                f"  Uptime: {int(uptime)}s ({int(uptime / 3600)}h {int((uptime % 3600) / 60)}m)"
            )

            diag.append("=" * 60)

            # Log all at once
            for line in diag:
                self.logger.info(line)

        except Exception as e:
            self.logger.error(f"[DIAGNOSTIC] Failed to dump state: {e}")

    def _watchdog_loop(self):
        """
        Watchdog thread to detect when main loop is stuck.
        Runs independently and logs CRITICAL warning if no progress detected.
        After 3 consecutive stuck detections (~6 minutes), forces process exit
        so the Windows scheduled task can restart the helper automatically.
        """
        WATCHDOG_INTERVAL = 120  # Check every 2 minutes
        MAX_STUCK_BEFORE_EXIT = 3  # Force exit after this many consecutive detections

        while self.running and not self.shutdown_event.is_set():
            try:
                time.sleep(WATCHDOG_INTERVAL)

                if not self.running:
                    break

                current_counter = self._watchdog_counter

                # Check if main loop has progressed
                if current_counter == self._last_watchdog_check and current_counter > 0:
                    self._stuck_count += 1
                    # Main loop is STUCK!
                    self.logger.critical("=" * 70)
                    self.logger.critical("[WATCHDOG] MAIN LOOP APPEARS STUCK!")
                    self.logger.critical(
                        f"[WATCHDOG] Loop counter stuck at: {current_counter}"
                    )
                    self.logger.critical(
                        f"[WATCHDOG] Stuck detection #{self._stuck_count}/{MAX_STUCK_BEFORE_EXIT}"
                    )
                    self.logger.critical(
                        f"[WATCHDOG] Heartbeat counter: {self.heartbeat_counter}"
                    )
                    self.logger.critical(
                        f"[WATCHDOG] Core connected: {self.core_connected}"
                    )

                    # Try to get stack traces of all threads
                    try:
                        import sys
                        import traceback

                        self.logger.critical("[WATCHDOG] Thread stack traces:")
                        for thread_id, frame in sys._current_frames().items():
                            self.logger.critical(f"--- Thread {thread_id} ---")
                            for line in traceback.format_stack(frame):
                                for subline in line.strip().split("\n"):
                                    self.logger.critical(f"    {subline}")
                    except Exception as e:
                        self.logger.critical(
                            f"[WATCHDOG] Could not get stack traces: {e}"
                        )

                    self.logger.critical("=" * 70)

                    # SELF-HEAL: Force exit after repeated stuck detections
                    if self._stuck_count >= MAX_STUCK_BEFORE_EXIT:
                        self.logger.critical(
                            f"[WATCHDOG] Main loop stuck for {self._stuck_count * WATCHDOG_INTERVAL}s "
                            f"— forcing process exit for scheduled-task restart"
                        )
                        import os as _os

                        _os._exit(1)  # Hard exit — scheduled task will restart us
                else:
                    # Main loop is progressing — reset stuck counter
                    self._stuck_count = 0
                    self.logger.debug(
                        f"[WATCHDOG] Main loop healthy: {current_counter} iterations"
                    )

                self._last_watchdog_check = current_counter

            except Exception as e:
                self.logger.error(f"[WATCHDOG] Error: {e}")

    def _setup_logging(self):
        """Configure structured JSON logging with rotation"""
        self.config.state_dir.mkdir(parents=True, exist_ok=True)
        self.config.log_file.parent.mkdir(parents=True, exist_ok=True)

        try:
            from logger import setup_logger
        except ImportError:
            import sys
            from pathlib import Path

            sys.path.insert(0, str(Path(__file__).parent.parent))
            from logger import setup_logger

        self.logger = setup_logger(
            "SentinelHelper", str(self.config.log_file), logging.INFO
        )

    def _wait_for_core(self, timeout: int = 60) -> bool:
        """Wait for core service to be ready"""
        self.logger.info("Waiting for core service...")

        start_time = time.time()
        retry_interval = 2

        while time.time() - start_time < timeout:
            if self.communicator.ping():
                self.core_connected = True
                self.connection_retry_count = 0
                elapsed = time.time() - start_time
                self.logger.info(
                    f"[OK] Connected to core service (after {elapsed:.1f}s)"
                )
                return True

            time.sleep(retry_interval)
            retry_interval = min(retry_interval * 1.5, 10)  # Exponential backoff

        self.logger.error(f"[FAIL] Failed to connect to core after {timeout}s")
        return False

    def _reconnect_to_core(self) -> bool:
        """Attempt to reconnect to core service with quick retries"""
        self.connection_retry_count += 1

        # Only log every 3rd attempt to reduce noise
        if self.connection_retry_count == 1 or self.connection_retry_count % 3 == 0:
            self.logger.warning(
                f"Reconnecting to core (attempt #{self.connection_retry_count})..."
            )

        # Quick retry loop - 3 attempts over 6 seconds max
        for attempt in range(3):
            if self.communicator.ping():
                self.core_connected = True
                self.connection_retry_count = 0
                self.logger.info("[OK] Reconnected to core service")
                return True
            time.sleep(2)

        # Only log failure on first attempt or every 6th failure
        if self.connection_retry_count == 1 or self.connection_retry_count % 6 == 0:
            self.logger.warning(
                f"[WARN] Core not reachable (attempt #{self.connection_retry_count})"
            )

        return False

    def run(self):
        """Main run loop with enhanced error handling"""
        self.running = True

        # Start watchdog FIRST - before anything else
        # This ensures we can detect hangs during identity sync or any early startup
        watchdog_thread = Thread(
            target=self._watchdog_loop, daemon=True, name="Watchdog"
        )
        watchdog_thread.start()
        self.logger.info("[WATCHDOG] Watchdog thread started")

        # STEP 1: Sync identity from Core first
        self.logger.info("[SYNC] Syncing identity from Core...")

        # Try loading from cache first (faster startup)
        identity_valid = self.identity_sync.load_cached_identity()

        # Loop until we can sync from Core (or have valid cached identity)
        # This effectively waits for Core to be available AND ensures we have credentials
        while not identity_valid and not self.shutdown_event.is_set():
            if self.identity_sync.sync_from_core():
                identity_valid = True
                self.logger.info("[SYNC] Successfully synced identity from Core")
            else:
                self.logger.warning("[SYNC] Failed to sync identity, retrying in 5s...")
                time.sleep(5)

        if self.shutdown_event.is_set():
            return

        # Start state detector for reliable lock/unlock detection
        self.state_detector.start()
        self.logger.info("[STATE] State detector started")

        # STEP 2: Verify authenticated connection
        if not self._wait_for_core(timeout=60):
            self.logger.error(
                "Core service available but authentication failed, will retry..."
            )
            self.core_connected = False
        else:
            self.core_connected = True

        if self.core_connected:
            # Run initial collection in background thread so heartbeats start immediately.
            # The Core's HelperMonitor expects heartbeats within 2 min, but initial
            # collection (especially extended inventory) can take 3-10 min.
            init_thread = Thread(
                target=self._send_initial_collections,
                daemon=True,
                name="InitialCollections",
            )
            init_thread.start()
            self.logger.info("[INIT] Initial collections started in background")

        # Main loop
        last_heartbeat = time.time()
        last_domain_check = time.time()
        last_inventory_check = time.time()
        last_hardware_check = time.time()
        last_ext_inventory_check = time.time()
        last_security_check = time.time()
        last_system_visibility_check = time.time()
        last_eol_check = time.time()
        last_connection_check = time.time()
        last_resource_check = time.time()
        last_network_change_check = time.time()
        was_suspended = False  # Track suspend→resume transitions

        consecutive_heartbeat_failures = 0
        max_consecutive_failures = 5

        # Initialize performance monitoring (CPU throttler + memory enforcer)
        perf = init_performance_monitoring()
        cpu_throttler = perf["cpu_throttler"]
        memory_enforcer = perf["memory_enforcer"]
        self.logger.info("[PERF] Performance monitoring active (CPU/Memory limits)")

        self.logger.info("Entering main monitoring loop...")
        loop_iteration = 0

        fatal_loop_error = False
        try:
            while self.running and not self.shutdown_event.is_set():
                loop_iteration += 1
                self._watchdog_counter = loop_iteration  # Update watchdog counter
                now = time.time()

                # ── Post-resume reconnection ────────────────────────
                # After sleep/wake the network likely changed (office→home).
                # Force a reconnection check so we don't silently fail.
                currently_suspended = self.state_detector.is_suspended()
                if was_suspended and not currently_suspended:
                    self.logger.info(
                        "[RESUME] System resumed from sleep — forcing reconnection check"
                    )
                    self.core_connected = False  # Force re-validate
                    was_suspended = False
                elif currently_suspended:
                    was_suspended = True

                # Periodic connection check (every 30 seconds)
                if now - last_connection_check >= 30:
                    if not self.core_connected:
                        self._reconnect_to_core()

                    # Check for config reload
                    if self.config.check_for_reload():
                        self.logger.info("[CONFIG] Config reloaded")

                    last_connection_check = now

                # Skip data collection if not connected
                if not self.core_connected:
                    time.sleep(5)
                    continue

                # Safety check: ensure identity is synced before sending data
                if self.config.agent_id == "pending":
                    self.logger.warning(
                        "[SYNC] Identity not synced, calling sync_identity()"
                    )
                    self.identity_sync.sync_from_core()

                # Adaptive Polling Interval
                # Use slower polling if idle or locked to save CPU
                # Use faster polling if active for better resolution
                # NOTE: heartbeat_interval is base (e.g. 30s)
                # Active: 30s
                # Idle: 60s
                # Locked: 120s

                # Get last idle state from collector
                # We can peek at internal state or just use base interval
                # Ideally, DataCollector exposes current state without sampling
                # But since we sample in _send_heartbeat, we can adjust NEXT interval based on CURRENT result

                # Determine current interval (default to base)
                current_interval = self.config.heartbeat_interval

                # If we have recent heartbeat data, adjust
                # (Simple approach: check collector internals or last logged state)
                # For now, stick to config.heartbeat_interval to avoid drift issues
                # But implementing Adaptive Polling as requested:

                if hasattr(self.collector, "_last_idle_state"):
                    state = self.collector._last_idle_state
                    if state == "locked":
                        current_interval = 120  # 2 minutes
                    elif state == "idle":
                        current_interval = 60  # 1 minute

                # Heartbeat (idle + foreground app)
                # Only force an early flush when the cached final-day totals are
                # actually valid.  Stale/corrupted data (total > 86400s) must NOT
                # trigger a burst — collector.py will discard it on the next regular
                # heartbeat.  Forcing a flush with bad data just fills the log with
                # REJECTED entries every 1s until the flag is cleared.
                _pending_final = getattr(
                    self.state_detector, "_final_totals_for_upload", None
                )
                if isinstance(_pending_final, dict):
                    _pf_total = (
                        _pending_final.get("active_seconds", 0)
                        + _pending_final.get("idle_seconds", 0)
                        + _pending_final.get("locked_seconds", 0)
                        + _pending_final.get("away_seconds", 0)
                    )
                    force_midnight_flush = _pf_total <= 86400
                else:
                    force_midnight_flush = False
                if force_midnight_flush or (now - last_heartbeat >= current_interval):
                    success = self._send_heartbeat()
                    last_heartbeat = now

                    if success:
                        consecutive_heartbeat_failures = 0
                        self.last_activity_time = datetime.now(timezone.utc)
                    else:
                        consecutive_heartbeat_failures += 1
                        self.logger.warning(
                            f"Heartbeat failed ({consecutive_heartbeat_failures}/{max_consecutive_failures})"
                        )

                        if consecutive_heartbeat_failures >= max_consecutive_failures:
                            self.logger.error(
                                "Too many consecutive failures, checking core connection..."
                            )
                            self.core_connected = False
                            consecutive_heartbeat_failures = 0

                # State Span Collection (NEW: Idempotent session tracking)
                if self.core_connected:
                    self._send_state_spans()

                # Domain collection (every heartbeat for active tracking)
                if now - last_domain_check >= self.config.heartbeat_interval:
                    if self.core_connected:
                        # NEW: Send domain sessions (active tracking)
                        self._send_domain_sessions()
                        # LEGACY: Send domain history visits (throttled internally)
                        self._send_domains()
                    last_domain_check = now

                # Inventory check (every 5 minutes)
                if now - last_inventory_check >= 120:
                    if self.core_connected:
                        self._check_inventory()
                    last_inventory_check = now

                # Hardware check (every 24 hours)
                if now - last_hardware_check >= 86400:  # 24h
                    if self.core_connected:
                        self._check_hardware()
                    last_hardware_check = now

                # EOL data check (every 24 hours)
                if now - last_eol_check >= 86400:  # 24h
                    if self.core_connected:
                        self._check_eol_data()
                    last_eol_check = now

                # Extended inventory check (every 6 hours)
                if now - last_ext_inventory_check >= 21600:  # 6h
                    if self.core_connected:
                        self._check_extended_inventory()
                    last_ext_inventory_check = now

                # Network change check (every 5 minutes)
                network_check_interval = 300  # 5 min
                if now - last_network_change_check >= network_check_interval:
                    if self.core_connected:
                        self._check_network_change()
                    last_network_change_check = now
                
                # Security indicators check (configurable, default every 6 hours)
                security_interval = max(
                    600, int(self.config.security_collection_interval_seconds)
                )
                if now - last_security_check >= security_interval:
                    if self.core_connected and self.config.enable_security_collection:
                        self._check_security_indicators()
                    last_security_check = now

                # Raw system visibility check (configurable, default every 6 hours)
                visibility_interval = max(
                    600, int(self.config.system_visibility_interval_seconds)
                )
                if now - last_system_visibility_check >= visibility_interval:
                    if (
                        self.core_connected
                        and self.config.enable_system_visibility_collection
                    ):
                        self._check_system_visibility()
                    last_system_visibility_check = now

                # Log health status every 30 iterations
                if loop_iteration % 30 == 0:
                    uptime = (
                        datetime.now(timezone.utc) - self.startup_time
                    ).total_seconds()
                    hours = int(uptime / 3600)
                    minutes = int((uptime % 3600) / 60)
                    self.logger.debug(
                        f"[HEALTH] Health: Uptime {hours}h {minutes}m, "
                        f"Heartbeats: {self.heartbeat_counter}, "
                        f"Domains: {self.domain_counter}, "
                        f"Connected: {self.core_connected}"
                    )

                # DIAGNOSTIC: Comprehensive state dump every 60 iterations (1-2 minutes)
                # This helps catch silent failures
                if loop_iteration % 60 == 0:
                    self._log_diagnostic_state(loop_iteration, current_interval)

                # ============================================================
                # PERF: CPU Throttling & Memory Limit Check (every 30 seconds)
                # ============================================================
                if now - last_resource_check >= 30:
                    # Update CPU limit based on system state
                    if hasattr(self.collector, "_last_idle_state"):
                        cpu_throttler.set_state(self.collector._last_idle_state)

                    # Check and enforce memory limit
                    try:
                        mem_result = memory_enforcer.check_and_enforce()
                        if mem_result["action_taken"]:
                            self.logger.info(
                                f"[PERF] Memory: {mem_result['usage_mb']:.1f}MB, "
                                f"action: {mem_result['action_taken']}"
                            )
                    except MemoryError as e:
                        # Memory limit exceeded with 'restart' action
                        self.logger.critical(f"[PERF] {e} - requesting restart")
                        raise  # Will be caught by crash handler

                    last_resource_check = now

                # CPU throttle check (runs on every loop)
                cpu_throttler.throttle_if_needed()

                # Sleep briefly
                time.sleep(1)

        except KeyboardInterrupt:
            self.logger.info("Shutdown requested via Ctrl+C")
        except Exception as e:
            fatal_loop_error = True
            self.logger.error(f"Fatal error in main loop: {e}", exc_info=True)
        finally:
            self.stop(crashed=fatal_loop_error)

    def _send_initial_collections(self):
        """Run all initial collections in a background thread.

        This allows the main monitoring loop (and heartbeats) to start
        immediately, preventing the Core HelperMonitor from killing us
        during the 3-10 min initial collection window.
        """
        try:
            self._send_initial_inventory()
            self._send_initial_hardware()
            self._send_initial_extended_inventory()
            if self.config.enable_security_collection:
                self._send_initial_security_indicators()
            else:
                self.logger.info("[SECURITY] Initial collection disabled by config")
            if self.config.enable_system_visibility_collection:
                self._send_initial_system_visibility()
            else:
                self.logger.info("[VISIBILITY] Initial collection disabled by config")

            # Send startup state event
            try:
                current_state = self.state_detector.get_state()
                startup_payload = {
                    "previous_state": "startup",
                    "current_state": current_state.value,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "duration_seconds": 0,
                }
                self.logger.info(
                    f"[STATE] Sending startup state: startup -> {current_state.value}"
                )
                success = self.communicator.send_state_change(startup_payload)
                if success:
                    self.logger.info("[STATE] Startup state event sent successfully")
                else:
                    self.logger.warning("[STATE] Failed to send startup state event")
            except Exception as e:
                self.logger.error(f"[STATE] Error sending startup state: {e}")

            self.logger.info("[INIT] All initial collections completed")
        except Exception as e:
            self.logger.error(f"[INIT] Initial collection error: {e}", exc_info=True)

    def _send_initial_inventory(self):
        """Send initial inventory on startup"""
        try:
            self.logger.info("Collecting initial inventory...")
            inventory = self.collector.collect_inventory(force=True)

            if inventory:
                if self.communicator.send_inventory(inventory):
                    self.logger.info(
                        f"[OK] Initial inventory sent: {len(inventory['apps'])} apps"
                    )
                else:
                    self.logger.warning("[FAIL] Failed to send initial inventory")
            else:
                self.logger.warning("No inventory data collected")

        except Exception as e:
            self.logger.error(f"Error sending initial inventory: {e}", exc_info=True)

    def _send_heartbeat(self) -> bool:
        """Collect and send heartbeat with explicit system_state"""
        try:
            # Collect heartbeat data
            heartbeat = self.collector.collect_heartbeat()

            # Add explicit system_state from state detector
            # This is the source of truth for lock/unlock detection
            current_state = self.state_detector.get_state()
            heartbeat["system_state"] = current_state.value

            # Send to core
            if self.communicator.send_heartbeat(heartbeat):
                self.heartbeat_counter += 1

                # Log with current state info
                self.logger.info(
                    f"Heartbeat #{heartbeat['sequence']}: "
                    f"system_state={current_state.value}, "
                    f"app={heartbeat['app']['current']}"
                )
                return True
            else:
                self.logger.warning("Failed to send heartbeat")
                return False

        except Exception as e:
            self.logger.error(f"Heartbeat error: {e}", exc_info=True)
            return False

    def _send_state_spans(self):
        """Collect and send completed state spans to core"""
        try:
            spans = self.collector.collect_state_spans()
            if spans:
                if self.communicator.send_state_spans(spans):
                    self.logger.info(f"[OK] Sent {len(spans)} state spans to core")
                else:
                    self.logger.warning(
                        f"[FAIL] Failed to send {len(spans)} state spans to core"
                    )
        except Exception as e:
            self.logger.error(f"Error sending state spans: {e}")

    def _on_state_change(
        self, old_state: SystemState, new_state: SystemState, duration_seconds: float
    ):
        """
        Handle state transitions from state detector with duration tracking.
        Sends immediate state-change telemetry to Core via CoreCommunicator.

        Args:
            old_state: Previous system state
            new_state: New system state
            duration_seconds: Time spent in previous state
        """
        self.system_state = new_state
        self.logger.info(
            f"[STATE] Transition: {old_state.value} -> {new_state.value} (d={duration_seconds:.1f}s)"
        )

        # Send immediate state change via CoreCommunicator (already has auth)
        try:
            import os

            payload = {
                "event_type": "state-change",
                "previous_state": old_state.value,
                "current_state": new_state.value,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "duration_seconds": int(duration_seconds),  # ✅ ADD THIS
                "username": os.getlogin(),  # Add username context
            }

            # Use existing communicator (no need for requests module)
            success = self.communicator.send_state_change(payload)

            if success:
                self.logger.info(
                    f"[STATE] State-change sent: {old_state.value} -> {new_state.value} "
                    f"(duration={int(duration_seconds)}s)"
                )
            else:
                self.logger.warning(
                    f"[STATE] State-change failed (will retry on next heartbeat)"
                )

        except Exception as e:
            self.logger.error(f"[STATE] Error sending state-change: {e}", exc_info=True)

    def _send_domains(self):
        """Collect and send domain visits (LEGACY - history-based)"""
        try:
            domains = self.collector.collect_domains()

            if domains:
                if self.communicator.send_domains(domains):
                    self.domain_counter += len(domains)
                    self.logger.debug(
                        f"[OK] Sent {len(domains)} domain visits (history)"
                    )
                else:
                    self.logger.warning("Failed to send domain visits")
            else:
                self.logger.debug("No new domain history to send")

        except Exception as e:
            self.logger.error(f"Domain history collection error: {e}", exc_info=True)

    def _send_domain_sessions(self):
        """Collect and send domain usage sessions (NEW - session-based)"""
        try:
            sessions = self.collector.collect_domain_sessions()

            if sessions:
                if self.communicator.send_domain_sessions(sessions):
                    total_duration = sum(s.get("duration_seconds", 0) for s in sessions)
                    self.logger.info(
                        f"[OK] Sent {len(sessions)} domain sessions "
                        f"({total_duration:.0f}s total)"
                    )
                else:
                    self.logger.warning("Failed to send domain sessions")
            else:
                self.logger.debug("No domain sessions to send")

        except Exception as e:
            self.logger.error(f"Domain session collection error: {e}", exc_info=True)

    def _check_inventory(self):
        """Check and send inventory if needed"""
        try:
            inventory = self.collector.collect_inventory()

            if inventory and inventory["changes"]["changed"]:
                if self.communicator.send_inventory(inventory):
                    changes = inventory["changes"]
                    self.logger.info(
                        f"[OK] Inventory update: "
                        f"+{len(changes['installed'])} "
                        f"-{len(changes['uninstalled'])} "
                        f"^{len(changes['updated'])}"
                    )
                else:
                    self.logger.warning("Failed to send inventory")
            else:
                self.logger.debug("No inventory changes detected")

        except Exception as e:
            self.logger.error(f"Inventory check error: {e}", exc_info=True)

    def _send_initial_hardware(self):
        """Send initial hardware info on startup"""
        try:
            self.logger.info("Collecting initial hardware info...")
            hardware = self.collector.collect_hardware(force=True)

            if hardware:
                if self.communicator.send_hardware(hardware):
                    self.logger.info(
                        f"[OK] Initial hardware sent: "
                        f"{hardware.get('identity', {}).get('manufacturer', '')} "
                        f"{hardware.get('identity', {}).get('model', '')}"
                    )
                else:
                    self.logger.warning("[FAIL] Failed to send initial hardware")
            else:
                self.logger.warning("No hardware data collected")

        except Exception as e:
            self.logger.error(f"Error sending initial hardware: {e}", exc_info=True)

    def _send_initial_extended_inventory(self):
        """Send initial extended inventory on startup"""
        try:
            self.logger.info("Collecting initial extended inventory...")
            data = self.collector.collect_extended_inventory(force=True)

            if data:
                if self.communicator.send_extended_inventory(data):
                    counts = {k: len(v) for k, v in data.items() if isinstance(v, list)}
                    self.logger.info(f"[OK] Initial extended inventory sent: {counts}")
                else:
                    self.logger.warning(
                        "[FAIL] Failed to send initial extended inventory"
                    )
            else:
                self.logger.warning("No extended inventory data collected")

        except Exception as e:
            self.logger.error(
                f"Error sending initial extended inventory: {e}", exc_info=True
            )

    def _check_extended_inventory(self):
        """Check and send extended inventory if due"""
        try:
            data = self.collector.collect_extended_inventory()
            if data:
                if self.communicator.send_extended_inventory(data):
                    counts = {k: len(v) for k, v in data.items() if isinstance(v, list)}
                    self.logger.info(f"[OK] Extended inventory update sent: {counts}")
                else:
                    self.logger.warning("Failed to send extended inventory update")
        except Exception as e:
            self.logger.error(f"Extended inventory check error: {e}")

    def _send_initial_security_indicators(self):
        """Send initial security analysis on startup"""
        if not self.config.enable_security_collection:
            self.logger.debug("[SECURITY] Initial collection skipped (disabled)")
            return

        try:
            self.logger.info("Running initial security analysis...")
            # Get extended inventory data to pass to security analyzer
            ext_data = None
            if hasattr(self.collector, "_ext_collector"):
                ext_data = self.collector._ext_collector.collect_all()

            data = self.collector.collect_security_indicators(
                force=True, ext_data=ext_data
            )

            if data:
                total = len(data.get("indicators", []))
                if self.communicator.send_security_indicators(data):
                    self.logger.info(
                        f"[OK] Initial security indicators sent: {total} indicators"
                    )
                else:
                    self.logger.warning(
                        "[FAIL] Failed to send initial security indicators"
                    )
            else:
                self.logger.info("No security indicators found (clean state)")

        except Exception as e:
            self.logger.error(
                f"Error sending initial security indicators: {e}", exc_info=True
            )

    def _check_security_indicators(self):
        """Check and send security indicators if due"""
        if not self.config.enable_security_collection:
            return

        try:
            # Pass cached ext inventory if available
            ext_data = None
            if hasattr(self.collector, "_ext_collector"):
                try:
                    ext_data = self.collector._ext_collector.collect_all()
                except Exception:
                    pass

            data = self.collector.collect_security_indicators(ext_data=ext_data)
            if data:
                total = len(data.get("indicators", []))
                if self.communicator.send_security_indicators(data):
                    self.logger.info(
                        f"[OK] Security indicators update sent: {total} indicators"
                    )
                else:
                    self.logger.warning("Failed to send security indicators update")
        except Exception as e:
            self.logger.error(f"Security indicators check error: {e}")

    def _send_initial_system_visibility(self):
        """Send initial raw system visibility snapshot on startup."""
        if not self.config.enable_system_visibility_collection:
            self.logger.debug("[VISIBILITY] Initial collection skipped (disabled)")
            return

        try:
            self.logger.info("Running initial raw system visibility collection...")
            data = self.collector.collect_system_visibility(force=True)
            if data:
                counts = data.get("counts", {})
                if self.communicator.send_system_visibility(data):
                    self.logger.info(f"[OK] Initial system visibility sent: {counts}")
                else:
                    self.logger.warning(
                        "[FAIL] Failed to send initial system visibility"
                    )
            else:
                self.logger.info("No system visibility snapshot generated")
        except Exception as e:
            self.logger.error(
                f"Error sending initial system visibility: {e}", exc_info=True
            )

    def _check_system_visibility(self):
        """Check and send raw system visibility snapshot if due."""
        if not self.config.enable_system_visibility_collection:
            return

        try:
            data = self.collector.collect_system_visibility()
            if data:
                counts = data.get("counts", {})
                if self.communicator.send_system_visibility(data):
                    self.logger.info(f"[OK] System visibility update sent: {counts}")
                else:
                    self.logger.warning("Failed to send system visibility update")
        except Exception as e:
            self.logger.error(f"System visibility check error: {e}")

    def _check_eol_data(self):
        """Check and send EOL data"""
        try:
            eol_data = self.collector.collect_eol_data()

            if eol_data:
                if self.communicator.send_eol_data(eol_data):
                    # Count items for logging
                    counts = {}
                    if "updates" in eol_data:
                        counts["updates"] = len(eol_data["updates"])
                    if "metering" in eol_data:
                        counts["metering"] = len(eol_data["metering"])
                    if "product_keys" in eol_data:
                        counts["product_keys"] = len(eol_data["product_keys"])
                    if "esu" in eol_data:
                        counts["esu"] = 1
                    if "warranty" in eol_data:
                        counts["warranty"] = 1
                    self.logger.info(f"[OK] EOL data sent: {counts}")
                else:
                    self.logger.warning("Failed to send EOL data")
            else:
                self.logger.debug("No EOL data to send (not due yet)")

        except Exception as e:
            self.logger.error(f"EOL data check error: {e}", exc_info=True)

    def _check_hardware(self):
        """Check and send hardware if changed"""
        try:
            hardware = self.collector.collect_hardware()

            if hardware:
                if self.communicator.send_hardware(hardware):
                    self.logger.info("[OK] Hardware update sent")
                else:
                    self.logger.warning("Failed to send hardware update")
            else:
                self.logger.debug("No hardware changes detected")

        except Exception as e:
            self.logger.error(f"Hardware check error: {e}", exc_info=True)
    
    def _check_network_change(self):
        """
        Check if network adapters have changed and send partial update.
        This is called every 5 minutes to detect WiFi/Ethernet switches.
        """
        try:
            network_data = self.collector.collect_network_partial()
            
            if network_data:
                if self.communicator.send_network_partial(network_data):
                    self.logger.info("[OK] Network partial update sent")
                else:
                    self.logger.warning("Failed to send network partial update")
            else:
                self.logger.debug("No network changes detected")

        except Exception as e:
            self.logger.error(f"Network change check error: {e}", exc_info=True)
    
    def stop(self, crashed: bool = False):
        """Stop helper gracefully"""
        self.logger.info("Stopping helper...")
        self.running = False
        self.shutdown_event.set()

        # Mark stop reason in state machine BEFORE stopping state detector.
        try:
            if crashed:
                self.state_detector.screen_time_engine.mark_crash()
                self.logger.info("[STATE] Marked CRASH in state machine")
            else:
                self.state_detector.screen_time_engine.mark_shutdown()
                self.logger.info("[STATE] Marked SHUTDOWN in state machine")
        except Exception as e:
            self.logger.error(f"Error marking stop reason: {e}")

        # Stop state detector
        try:
            self.state_detector.stop()
            self.logger.info("[STATE] State detector stopped")
        except Exception as e:
            self.logger.error(f"Error stopping state detector: {e}")

        # End any active domain sessions before shutdown
        try:
            self.collector.shutdown()
            # Send final domain sessions
            final_sessions = self.collector.collect_domain_sessions()
            if final_sessions and self.core_connected:
                self.communicator.send_domain_sessions(final_sessions)
                self.logger.info(
                    f"[OK] Sent {len(final_sessions)} final domain sessions"
                )
        except Exception as e:
            self.logger.error(f"Error during shutdown cleanup: {e}")

        # Calculate uptime
        uptime = (datetime.now(timezone.utc) - self.startup_time).total_seconds()
        hours = int(uptime / 3600)
        minutes = int((uptime % 3600) / 60)
        seconds = int(uptime % 60)

        # Send final stats
        self.logger.info("=" * 60)
        self.logger.info("Session Summary:")
        self.logger.info(f"  Uptime: {hours}h {minutes}m {seconds}s")
        self.logger.info(f"  Heartbeats sent: {self.heartbeat_counter}")
        self.logger.info(f"  Domain visits tracked: {self.domain_counter}")
        self.logger.info(f"  Connection retries: {self.connection_retry_count}")
        self.logger.info("=" * 60)
        self.logger.info("Helper stopped cleanly")


# ============================================================================
# BUG-003: Crash Handler
# ============================================================================
def write_crash_dump(exc_type, exc_value, exc_traceback):
    """Write crash dump to file for debugging"""
    import traceback
    from datetime import datetime
    import os

    program_data = os.environ.get("ProgramData", r"C:\ProgramData")
    # Check stealth name first, then legacy
    for dirname in ["WinDiagSvc", "SentinelEdge"]:
        candidate = os.path.join(program_data, dirname, "logs")
        if os.path.isdir(candidate):
            crash_dir = candidate
            break
    else:
        crash_dir = os.path.join(program_data, "WinDiagSvc", "logs")
    os.makedirs(crash_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    crash_file = os.path.join(crash_dir, f"helper_crash_{timestamp}.txt")

    try:
        with open(crash_file, "w") as f:
            f.write("=" * 70 + "\n")
            f.write("Agent Helper - CRASH DUMP\n")
            f.write(f"Time: {datetime.now().isoformat()}\n")
            f.write("=" * 70 + "\n\n")

            f.write("Exception Type: " + str(exc_type.__name__) + "\n")
            f.write("Exception Value: " + str(exc_value) + "\n\n")

            f.write("Traceback:\n")
            f.write("-" * 70 + "\n")
            traceback.print_exception(exc_type, exc_value, exc_traceback, file=f)
            f.write("-" * 70 + "\n\n")

            # System info
            import platform

            f.write("System Info:\n")
            f.write(f"  OS: {platform.system()} {platform.release()}\n")
            f.write(f"  Python: {platform.python_version()}\n")
            f.write(f"  Machine: {platform.machine()}\n")

        return crash_file
    except Exception as e:
        return None


def main():
    """Entry point with crash handler"""
    import sys

    try:
        helper = SentinelHelper()
        helper.run()
    except KeyboardInterrupt:
        print("Helper interrupted by user")
        sys.exit(0)
    except SystemExit:
        raise  # Allow normal exits
    except Exception as e:
        # BUG-003: Catch all unhandled exceptions
        import traceback
        import logging

        logger = logging.getLogger("Helper.CrashHandler")

        # Write crash dump
        exc_info = sys.exc_info()
        crash_file = write_crash_dump(exc_info[0], exc_info[1], exc_info[2])

        logger.critical("=" * 70)
        logger.critical("HELPER CRASHED! Unhandled exception:")
        logger.critical(f"  Type: {type(e).__name__}")
        logger.critical(f"  Message: {e}")
        if crash_file:
            logger.critical(f"  Crash dump: {crash_file}")
        logger.critical("=" * 70)

        # Print to stderr as well
        print(f"\n!!! HELPER CRASHED: {e}", file=sys.stderr)
        traceback.print_exc()
        if crash_file:
            print(f"Crash dump written to: {crash_file}", file=sys.stderr)

        sys.exit(1)


if __name__ == "__main__":
    main()
