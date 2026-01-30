"""
Data Collector Module - ENHANCED
================================
Orchestrates all data collection and builds heartbeat packets.
Now includes session-based domain tracking integrated with app/idle tracking.
"""
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
import logging

from .idle import IdleDetector
from .window import WindowTracker
from .domain import ActiveDomainTracker, BrowserHistoryTracker
from .inventory import InventoryTracker
from .config import HelperConfig

# CPU fallback for when window tracking fails
try:
    from .cpu_fallback import CPUBasedTracker
    CPU_FALLBACK_AVAILABLE = True
except ImportError:
    CPU_FALLBACK_AVAILABLE = False

logger = logging.getLogger(__name__)


def validate_duration(value, default=0, max_value=86400, context="duration"):
    """Validate duration is a sane number (0-24 hours)."""
    try:
        val = float(value)
        if not (0 <= val <= max_value):
            logger.error(f"[VALIDATION] {context} out of range: {val}s, using {default}s")
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
    
    def __init__(self, config: HelperConfig):
        self.config = config
        self.state_detector = None  # Link set by main.py

        try:
            # Initialize enhanced modules
            logger.info("[INIT] Starting DataCollector initialization...")

            self.idle_detector = IdleDetector(
                config.idle_threshold,
                enable_app_specific_thresholds=config.enable_app_specific_thresholds,
                on_idle_complete=self.send_idle_event
            )
            logger.info("[INIT] ✓ IdleDetector")

            self.window_tracker = WindowTracker(
                capture_titles=config.capture_window_titles,
                state_file=config.data_dir / 'window_state.json'
            )
            logger.info("[INIT] ✓ WindowTracker")

            # Domain tracking - NEW: Active domain tracker for sessions
            self.active_domain_tracker = ActiveDomainTracker(config.capture_full_urls)
            logger.info("[INIT] ✓ ActiveDomainTracker")

            # Legacy history tracker (for backward compatibility)
            self.history_tracker = BrowserHistoryTracker(config.capture_full_urls)
            logger.info("[INIT] ✓ BrowserHistoryTracker")

            self.inventory_tracker = InventoryTracker(config)
            logger.info("[INIT] ✓ InventoryTracker")

            # State
            self.sequence_number = 0
            self.last_inventory_time = None
            self.app_durations = {}  # app_name -> cumulative seconds

            # Domain session state
            self._last_idle_state = 'active'
            self._last_foreground_app = None

            # Enhanced: Session tracking
            self._session_start = datetime.now(timezone.utc)
            self._heartbeat_count = 0

            # Track current date for midnight detection
            self._current_date = datetime.now(timezone.utc).date()

            # Track previous cumulative values for delta calculation
            self._prev_cumulative_active = 0.0
            self._prev_cumulative_idle = 0.0
            self._prev_cumulative_locked = 0.0

            # CPU fallback tracker for when window tracking fails
            self.cpu_tracker = CPUBasedTracker() if CPU_FALLBACK_AVAILABLE else None
            self.window_tracking_failures = 0
            self.use_cpu_fallback = False
            logger.info("[INIT] ✓ CPU fallback")

            # Load persisted state
            logger.info("[INIT] Loading persisted state...")
            self._load_state()
            logger.info("[INIT] ✓ State loaded")

            # Apply initial config
            logger.info("[INIT] Applying config...")
            self.apply_config()
            logger.info("[INIT] ✓ Config applied")

            logger.info("[COLLECTOR] Enhanced DataCollector initialized with session tracking")

        except Exception as e:
            logger.error("="*60)
            logger.error("[INIT] FATAL ERROR during DataCollector initialization!")
            logger.error(f"[INIT] Error type: {type(e).__name__}")
            logger.error(f"[INIT] Error message: {str(e)}")
            logger.error("="*60)
            import traceback
            logger.error(traceback.format_exc())
            logger.error("="*60)
            raise  # Re-raise to crash properly with full error

    
    def apply_config(self):
        """Apply configuration changes to sub-modules"""
        self.idle_detector.update_settings(
            self.config.idle_threshold,
            enable_app_specific_thresholds=self.config.enable_app_specific_thresholds
        )
        self.window_tracker.update_settings(self.config.capture_window_titles)
        self.active_domain_tracker.update_settings(self.config.capture_full_urls)
        self.history_tracker.update_settings(self.config.capture_full_urls)
        
    def _load_state(self):
        """Load persisted state"""
        try:
            if self.config.state_file.exists():
                with open(self.config.state_file, 'r') as f:
                    state = json.load(f)
                    self.sequence_number = state.get('sequence_number', 0)
                    self.app_durations = state.get('app_durations', {})
                    self.last_inventory_time = state.get('last_inventory_time')
                    
                    # Restore domain tracker states
                    if 'active_domain_state' in state:
                        self.active_domain_tracker.set_state(state['active_domain_state'])
                    if 'history_state' in state:
                        self.history_tracker.set_state(state['history_state'])
                    # Legacy compatibility
                    elif 'domain_state' in state:
                        self.history_tracker.set_state(state['domain_state'])
                        
        except Exception as e:
            logger.warning(f"Failed to load state: {e}")
    
    def _save_state(self):
        """Save state to disk"""
        try:
            state = {
                'sequence_number': self.sequence_number,
                'app_durations': self.app_durations,
                'last_inventory_time': self.last_inventory_time,
                'active_domain_state': self.active_domain_tracker.get_state(),
                'history_state': self.history_tracker.get_state(),
            }
            
            # Atomic write
            temp_file = self.config.state_file.with_suffix('.tmp')
            with open(temp_file, 'w') as f:
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
        now = datetime.now(timezone.utc)
        self.sequence_number += 1
        self._heartbeat_count += 1

        # Check for midnight crossing (new day)
        current_date = now.date()
        if current_date != self._current_date:
            logger.info(f"[COLLECTOR] Day changed: {self._current_date} → {current_date}")
            logger.info(f"[COLLECTOR] Resetting cumulative counters...")

            # Reset StateDetector cumulative counters (NEW: StateDetector is source of truth)
            if self.state_detector:
                self.state_detector.reset_cumulative()

            # Reset previous cumulative values for delta calculation (LEGACY - no longer used)
            self._prev_cumulative_active = 0.0
            self._prev_cumulative_idle = 0.0
            self._prev_cumulative_locked = 0.0

            # Update current date
            self._current_date = current_date
            self._session_start = now
            self._heartbeat_count = 0

            logger.info("[COLLECTOR] Cumulative counters reset for new day")
            
            # FIX: Reset WindowTracker timestamp to prevent overnight duration overflow
            if self.window_tracker:
                logger.info("[COLLECTOR] Resetting WindowTracker for new day...")
                # Save current app's duration before reset
                if hasattr(self.window_tracker, '_current_app') and self.window_tracker._current_app:
                    try:
                        old_duration = (now - self.window_tracker._app_start).total_seconds()
                        logger.info(f"[COLLECTOR] Previous session: {self.window_tracker._current_app} ({old_duration:.1f}s)")
                        
                        # Update cumulative usage if available
                        if hasattr(self.window_tracker, '_cumulative_app_usage') and hasattr(self.window_tracker, 'duration_lock'):
                            with self.window_tracker.duration_lock:
                                if self.window_tracker._current_app in self.window_tracker._cumulative_app_usage:
                                    self.window_tracker._cumulative_app_usage[self.window_tracker._current_app] += old_duration
                                else:
                                    self.window_tracker._cumulative_app_usage[self.window_tracker._current_app] = old_duration
                            
                            if hasattr(self.window_tracker, '_save_state'):
                                self.window_tracker._save_state()
                    except Exception as e:
                        logger.warning(f"[COLLECTOR] Error saving previous session: {e}")
                
                # Reset start time to NOW (prevents overnight overflow)
                self.window_tracker._app_start = now
                logger.info("[COLLECTOR] WindowTracker timestamp reset")
        
        # Drive state detection (NEW ARCHITECTURE)
        if self.state_detector:
            self.state_detector._update_state()
        
        # ====================================================================
        # STEP 1: Sample foreground window FIRST (needed for lock fallback)
        # ====================================================================
        window_change = None
        current_app = {'app_name': 'unknown', 'window_title': None, 'duration_seconds': 0}
        
        if self.config.enable_app_tracking:
            # Always sample window to detect lock screen apps (lockapp.exe)
            window_change = self.window_tracker.sample()
            current_app = self.window_tracker.get_current_app_duration()
        
        # ====================================================================
        # STEP 2: Get current authoritative state (with defensive guard)
        # ====================================================================
        current_state = self.get_system_state()
            
        idle_state = {
            'state': current_state,
            'changed': current_state != self._last_idle_state,
            'duration_seconds': 0  # Timing is now event-driven
        }
        
        # STEP 3: Re-evaluate app tracking based on idle state
        # ====================================================================
        if self.config.enable_app_tracking:
            is_idle = current_state in ['idle', 'locked']
            
            if is_idle:
                # User is IDLE/LOCKED - pause app tracking, clear current app
                current_app = {
                    'app_name': None,
                    'window_title': None,
                    'duration_seconds': 0,
                    'is_paused': True  # Flag to indicate tracking is paused
                }
            else:
                # User is ACTIVE - check window tracking health
                # Check if window tracking is failing
                if current_app.get('app_name') in ['unknown', None, '']:
                    self.window_tracking_failures += 1
                    
                    # After 3 consecutive failures, try CPU fallback
                    if self.window_tracking_failures >= 3 and self.cpu_tracker:
                        if not self.use_cpu_fallback:
                            logger.warning("[COLLECTOR] Window tracking failing, enabling CPU fallback")
                            self.use_cpu_fallback = True
                        
                        # Try CPU-based detection
                        cpu_app = self.cpu_tracker.get_active_app_by_cpu()
                        if cpu_app:
                            logger.debug(f"[COLLECTOR] Using CPU fallback: {cpu_app}")
                            current_app['app_name'] = cpu_app
                            current_app['detection_method'] = 'cpu_fallback'
                else:
                    # Window tracking is working
                    if self.window_tracking_failures > 0:
                        logger.info("[COLLECTOR] Window tracking recovered")
                    self.window_tracking_failures = 0
                    self.use_cpu_fallback = False
        
        # ====================================================================
        # NEW: Domain session tracking integrated with heartbeat
        # ====================================================================
        if self.config.enable_domains:
            current_idle = idle_state['state']
            is_idle = current_idle in ['idle', 'locked']
            
            # Handle idle state transitions for domain sessions
            if self._last_idle_state != 'idle' and current_idle == 'idle':
                # User became idle - end domain session
                self.active_domain_tracker.end_session_for_sleep()
            elif self._last_idle_state != 'locked' and current_idle == 'locked':
                # Workstation locked - end domain session
                self.active_domain_tracker.end_session_for_lock()
            
            # Sample domain (handles browser detection internally)
            foreground_app = current_app.get('app_name')
            window_title = current_app.get('window_title')
            
            self.active_domain_tracker.sample(
                foreground_app=foreground_app,
                window_title=window_title,
                is_idle=is_idle
            )
            
            # Track state for next cycle
            self._last_idle_state = current_idle
            self._last_foreground_app = foreground_app
        
        # ====================================================================
        # End domain session tracking
        # ====================================================================
        
        # Accumulate app durations
        if window_change and window_change.get('app_name'):
            app_name = window_change['app_name']
            duration = validate_duration(
                window_change.get('duration_seconds', 0),
                context=f"window_change[{window_change.get('app_name')}]"
            )

            if app_name in self.app_durations:
                self.app_durations[app_name] += duration
            else:
                self.app_durations[app_name] = duration
        
        # Calculate deltas for live tracking (simple interval-based)
        # Note: Precision accounting is now event-driven for idle sessions
        delta_active = 0
        delta_idle = 0
        delta_locked = 0
        
        if current_state == 'active':
            delta_active = self.config.heartbeat_interval
        elif current_state == 'idle':
            delta_idle = self.config.heartbeat_interval
        elif current_state == 'locked':
            delta_locked = self.config.heartbeat_interval

        # Keep these updated to prevent old drift logic from firing
        self._prev_cumulative_active = 0.0
        self._prev_cumulative_idle = 0.0
        self._prev_cumulative_locked = 0.0

        # Build simplified heartbeat packet
        heartbeat = {
            'agent_id': self.config.agent_id,
            'username': self.config.username,
            'sequence': self.sequence_number,
            'timestamp': now.isoformat(),
            'pulsetime': self.config.heartbeat_interval,
            'idempotency_key': f"{self.config.agent_id}_{self.sequence_number}",
            
            # Simple state info for live display
            'system_state': current_state,
            
            # Enhanced Foreground app info
            'app': {
                'current': current_app['app_name'],
                'friendly_name': current_app.get('friendly_name', current_app['app_name']),
                'current_title': current_app.get('window_title'),
                'is_browser': current_app.get('is_browser', False),
            },
            
            # Enhanced screentime info with deltas for Core aggregation
            'screentime': {
                'session_start': self._session_start.isoformat(),
                'heartbeat_count': self._heartbeat_count,
            }
        }
        
        # ✅ NEW: Add cumulative deltas from StateDetector
        if self.state_detector:
            deltas = self.state_detector.get_cumulative_deltas()
            heartbeat['screentime']['delta_active_seconds'] = int(deltas['delta_active_seconds'])
            heartbeat['screentime']['delta_idle_seconds'] = int(deltas['delta_idle_seconds'])
            heartbeat['screentime']['delta_locked_seconds'] = int(deltas['delta_locked_seconds'])
        
        # Add app change info if occurred
        if window_change and window_change.get('changed'):
            heartbeat['app']['changed'] = True
            heartbeat['app']['previous'] = window_change.get('app_name')
            heartbeat['app']['previous_duration'] = validate_duration(
                window_change.get('duration_seconds', 0),
                context=f"previous_duration[{window_change.get('app_name')}]"
            )
        
        # Add current domain session info (for debugging/display)
        domain_info = self.active_domain_tracker.get_current_session_info()
        if domain_info:
            heartbeat['domain'] = domain_info
        
        # Track state for next cycle
        self._last_idle_state = current_state
        self._last_foreground_app = current_app.get('app_name')

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
            'type': 'idle_event',
            'agent_id': self.config.agent_id,
            'state': 'idle',
            'duration_seconds': round(duration, 1),
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
        
        logger.info(f"[COLLECTOR] Dispatching clean idle event: {duration:.1f}s")
        # In a real implementation, this would queue for upload.
        # For now, we'll store it in a way the core can pick it up.
        # Or if there's a direct upload method, we'd call it.
        # Assuming DataCollector is responsible for 'emitting' which main.py handles.
        if hasattr(self, '_idle_events'):
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
                inventory['agent_id'] = self.config.agent_id
                
                self.last_inventory_time = datetime.now(timezone.utc).isoformat()
                self._save_state()
                
                return inventory
            
            return None
            
        except Exception as e:
            logger.error(f"Inventory collection error: {e}")
            return None
    
    def get_app_usage_summary(self) -> List[Dict]:
        """
        Get accumulated app usage for batch upload

        Returns:
            List of app usage dicts
        """
        summary = []
        for app_name, total_seconds in list(self.app_durations.items()):
            if total_seconds > 0:
                summary.append({
                    'app_name': app_name,
                    'total_seconds': total_seconds
                })

        # Clear accumulated durations after retrieval
        self.app_durations = {}

        self._save_state()
        return summary
    
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
