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
from helper.performance import get_cpu_throttler, get_memory_enforcer, init_performance_monitoring


class SentinelHelper:
    """Main helper process with enhanced resilience"""
    
    def __init__(self):
        # Load configuration
        self.config = HelperConfig()
        
        # Setup logging
        self._setup_logging()
        
        # Initialize components
        self.collector = DataCollector(self.config)
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
        
        # Connection state
        self.core_connected = False
        self.connection_retry_count = 0
        
        # State detector for reliable lock/unlock detection
        self.state_detector = StateDetector(
            idle_threshold_seconds=self.config.idle_threshold,
            on_state_change=self._on_state_change,
            agent_id=self.config.agent_id,
            data_dir=self.config.state_dir
        )
        self.system_state = SystemState.ACTIVE
        
        # Link components for state arbitration
        self.state_detector.idle_detector = self.collector.idle_detector
        self.collector.idle_detector.authority = self.state_detector.authority
        self.collector.state_detector = self.state_detector
        self.state_detector.collector = self.collector # Link for event emission
        
        self.logger.info("="*60)
        self.logger.info("SentinelEdge Helper v2.0 - Enhanced")
        self.logger.info(f"Agent ID: {self.communicator.agent_id}")
        self.logger.info(f"Core URL: {self.config.core_url}")
        self.logger.info(f"Heartbeat Interval: {self.config.heartbeat_interval}s")
        self.logger.info(f"Startup: {self.startup_time.isoformat()}")
        self.logger.info("="*60)
        
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
                diag.append(f"  Is Locked Flag: {self.state_detector.authority.state == SystemState.LOCKED}")
            except Exception as e:
                diag.append(f"  State Detector: ERROR - {e}")
            
            # 3. Collector state
            try:
                last_idle = getattr(self.collector, '_last_idle_state', 'unknown')
                last_app = getattr(self.collector, '_last_foreground_app', 'unknown')
                heartbeat_count = getattr(self.collector, '_heartbeat_count', 0)
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
                idle_detector_state = "idle" if self.collector.idle_detector.is_idle() else "active"
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
                diag.append(f"  Window Tracker App: {current_app.get('app_name', 'unknown')}")
                diag.append(f"  Window Tracker Duration: {current_app.get('duration_seconds', 0)}s")
            except Exception as e:
                diag.append(f"  Window Tracker: ERROR - {e}")
            
            # 6. Counters
            diag.append(f"  Heartbeats Sent: {self.heartbeat_counter}")
            diag.append(f"  Domains Sent: {self.domain_counter}")
            diag.append(f"  Connection Retries: {self.connection_retry_count}")
            
            # 7. Uptime
            uptime = (datetime.now(timezone.utc) - self.startup_time).total_seconds()
            diag.append(f"  Uptime: {int(uptime)}s ({int(uptime/3600)}h {int((uptime%3600)/60)}m)")
            
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
        """
        WATCHDOG_INTERVAL = 120  # Check every 2 minutes
        
        while self.running and not self.shutdown_event.is_set():
            try:
                time.sleep(WATCHDOG_INTERVAL)
                
                if not self.running:
                    break
                
                current_counter = self._watchdog_counter
                
                # Check if main loop has progressed
                if current_counter == self._last_watchdog_check and current_counter > 0:
                    # Main loop is STUCK!
                    self.logger.critical("=" * 70)
                    self.logger.critical("[WATCHDOG] MAIN LOOP APPEARS STUCK!")
                    self.logger.critical(f"[WATCHDOG] Loop counter stuck at: {current_counter}")
                    self.logger.critical(f"[WATCHDOG] Heartbeat counter: {self.heartbeat_counter}")
                    self.logger.critical(f"[WATCHDOG] Core connected: {self.core_connected}")
                    
                    # Try to get stack traces of all threads
                    try:
                        import sys
                        import traceback
                        
                        self.logger.critical("[WATCHDOG] Thread stack traces:")
                        for thread_id, frame in sys._current_frames().items():
                            self.logger.critical(f"--- Thread {thread_id} ---")
                            for line in traceback.format_stack(frame):
                                for subline in line.strip().split('\n'):
                                    self.logger.critical(f"    {subline}")
                    except Exception as e:
                        self.logger.critical(f"[WATCHDOG] Could not get stack traces: {e}")
                    
                    self.logger.critical("=" * 70)
                else:
                    # Main loop is progressing
                    self.logger.debug(f"[WATCHDOG] Main loop healthy: {current_counter} iterations")
                
                self._last_watchdog_check = current_counter
                
            except Exception as e:
                self.logger.error(f"[WATCHDOG] Error: {e}")
    
    def _setup_logging(self):
        """Configure logging with rotation"""
        self.config.state_dir.mkdir(parents=True, exist_ok=True)
        self.config.log_file.parent.mkdir(parents=True, exist_ok=True)
        
        from logging.handlers import RotatingFileHandler
        
        handlers = [
            RotatingFileHandler(
                self.config.log_file,
                maxBytes=5*1024*1024,  # 5MB
                backupCount=3
            ),
            logging.StreamHandler()
        ]
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s [%(levelname)s] %(message)s',
            handlers=handlers
        )
        self.logger = logging.getLogger('SentinelHelper')
    
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
                self.logger.info(f"[OK] Connected to core service (after {elapsed:.1f}s)")
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
            self.logger.warning(f"Reconnecting to core (attempt #{self.connection_retry_count})...")
        
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
            self.logger.warning(f"[WARN] Core not reachable (attempt #{self.connection_retry_count})")
        
        return False
    
    def run(self):
        """Main run loop with enhanced error handling"""
        self.running = True
        
        # Start watchdog FIRST - before anything else
        # This ensures we can detect hangs during identity sync or any early startup
        watchdog_thread = Thread(target=self._watchdog_loop, daemon=True, name="Watchdog")
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
            self.logger.error("Core service available but authentication failed, will retry...")
            self.core_connected = False
        else:
            self.core_connected = True
        
        # Send initial inventory if connected
        if self.core_connected:
            self._send_initial_inventory()
            
            # ============================================================
            # CRITICAL FIX: Send startup state event
            # This tells the server "agent just started in X state"
            # Without this, cross-day sessions get miscalculated
            # ============================================================
            try:
                current_state = self.state_detector.get_state()
                startup_payload = {
                    'previous_state': 'startup',  # Special marker for agent startup
                    'current_state': current_state.value,
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'duration_seconds': 0  # No duration for startup event
                }
                self.logger.info(f"[STATE] Sending startup state: startup → {current_state.value}")
                success = self.communicator.send_state_change(startup_payload)
                if success:
                    self.logger.info("[STATE] Startup state event sent successfully")
                else:
                    self.logger.warning("[STATE] Failed to send startup state event")
            except Exception as e:
                self.logger.error(f"[STATE] Error sending startup state: {e}")
        
        # Main loop
        last_heartbeat = time.time()
        last_domain_check = time.time()
        last_inventory_check = time.time()
        last_connection_check = time.time()
        last_resource_check = time.time()
        
        consecutive_heartbeat_failures = 0
        max_consecutive_failures = 5
        
        # Initialize performance monitoring (CPU throttler + memory enforcer)
        perf = init_performance_monitoring()
        cpu_throttler = perf['cpu_throttler']
        memory_enforcer = perf['memory_enforcer']
        self.logger.info("[PERF] Performance monitoring active (CPU/Memory limits)")
        
        self.logger.info("Entering main monitoring loop...")
        loop_iteration = 0
        
        try:
            while self.running and not self.shutdown_event.is_set():
                loop_iteration += 1
                self._watchdog_counter = loop_iteration  # Update watchdog counter
                now = time.time()
                
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
                    self.logger.warning("[SYNC] Identity not synced, calling sync_identity()")
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
                
                if hasattr(self.collector, '_last_idle_state'):
                    state = self.collector._last_idle_state
                    if state == 'locked':
                        current_interval = 120 # 2 minutes
                    elif state == 'idle':
                        current_interval = 60 # 1 minute
                
                # Heartbeat (idle + foreground app)
                if now - last_heartbeat >= current_interval:
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
                            self.logger.error("Too many consecutive failures, checking core connection...")
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
                
                # Log health status every 30 iterations
                if loop_iteration % 30 == 0:
                    uptime = (datetime.now(timezone.utc) - self.startup_time).total_seconds()
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
                    if hasattr(self.collector, '_last_idle_state'):
                        cpu_throttler.set_state(self.collector._last_idle_state)
                    
                    # Check and enforce memory limit
                    try:
                        mem_result = memory_enforcer.check_and_enforce()
                        if mem_result['action_taken']:
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
            self.logger.error(f"Fatal error in main loop: {e}", exc_info=True)
        finally:
            self.stop()
    
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
            heartbeat['system_state'] = current_state.value
            
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
                    self.logger.warning(f"[FAIL] Failed to send {len(spans)} state spans to core")
        except Exception as e:
            self.logger.error(f"Error sending state spans: {e}")
    
    def _on_state_change(self, old_state: SystemState, new_state: SystemState, duration_seconds: float):
        """
        Handle state transitions from state detector with duration tracking.
        Sends immediate state-change telemetry to Core via CoreCommunicator.
        
        Args:
            old_state: Previous system state
            new_state: New system state
            duration_seconds: Time spent in previous state
        """
        self.system_state = new_state
        self.logger.info(f"[STATE] Transition: {old_state.value} → {new_state.value} (Δ{duration_seconds:.1f}s)")
        
        # Send immediate state change via CoreCommunicator (already has auth)
        try:
            import os
            payload = {
                'event_type': 'state-change',
                'previous_state': old_state.value,
                'current_state': new_state.value,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'duration_seconds': int(duration_seconds),  # ✅ ADD THIS
                'username': os.getlogin()  # Add username context
            }
            
            # Use existing communicator (no need for requests module)
            success = self.communicator.send_state_change(payload)
            
            if success:
                self.logger.info(
                    f"[STATE] State-change sent: {old_state.value} → {new_state.value} "
                    f"(duration={int(duration_seconds)}s)"
                )
            else:
                self.logger.warning(f"[STATE] State-change failed (will retry on next heartbeat)")
                
        except Exception as e:
            self.logger.error(f"[STATE] Error sending state-change: {e}", exc_info=True)
    
    def _send_domains(self):
        """Collect and send domain visits (LEGACY - history-based)"""
        try:
            domains = self.collector.collect_domains()
            
            if domains:
                if self.communicator.send_domains(domains):
                    self.domain_counter += len(domains)
                    self.logger.debug(f"[OK] Sent {len(domains)} domain visits (history)")
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
                    total_duration = sum(s.get('duration_seconds', 0) for s in sessions)
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
            
            if inventory and inventory['changes']['changed']:
                if self.communicator.send_inventory(inventory):
                    changes = inventory['changes']
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
    
    def stop(self):
        """Stop helper gracefully"""
        self.logger.info("Stopping helper...")
        self.running = False
        self.shutdown_event.set()
        
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
                self.logger.info(f"[OK] Sent {len(final_sessions)} final domain sessions")
        except Exception as e:
            self.logger.error(f"Error during shutdown cleanup: {e}")
        
        # Calculate uptime
        uptime = (datetime.now(timezone.utc) - self.startup_time).total_seconds()
        hours = int(uptime / 3600)
        minutes = int((uptime % 3600) / 60)
        seconds = int(uptime % 60)
        
        # Send final stats
        self.logger.info("="*60)
        self.logger.info("Session Summary:")
        self.logger.info(f"  Uptime: {hours}h {minutes}m {seconds}s")
        self.logger.info(f"  Heartbeats sent: {self.heartbeat_counter}")
        self.logger.info(f"  Domain visits tracked: {self.domain_counter}")
        self.logger.info(f"  Connection retries: {self.connection_retry_count}")
        self.logger.info("="*60)
        self.logger.info("Helper stopped cleanly")


# ============================================================================
# BUG-003: Crash Handler
# ============================================================================
def write_crash_dump(exc_type, exc_value, exc_traceback):
    """Write crash dump to file for debugging"""
    import traceback
    from datetime import datetime
    import os
    
    program_data = os.environ.get('ProgramData', r'C:\ProgramData')
    crash_dir = os.path.join(program_data, 'SentinelEdge', 'logs')
    os.makedirs(crash_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    crash_file = os.path.join(crash_dir, f'helper_crash_{timestamp}.txt')
    
    try:
        with open(crash_file, 'w') as f:
            f.write("=" * 70 + "\n")
            f.write("SentinelEdge Helper - CRASH DUMP\n")
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
        
        logger = logging.getLogger('Helper.CrashHandler')
        
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


if __name__ == '__main__':
    main()