"""
Production-Grade State Detection System
Uses Windows Session Events for lock/unlock detection
"""

# Try to import pywin32 modules - if not available, use fallback
try:
    import win32api
    import win32con
    import win32gui
    import winerror
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False
    win32api = None
    win32con = None
    win32gui = None
    winerror = None

import ctypes
from ctypes import Structure, windll, byref, sizeof, c_uint
from datetime import datetime
from pathlib import Path
import threading
import logging
import time
import os
from enum import Enum
from typing import Callable, Optional

# ✅ PHASE 2: Import state machine (single source of truth)
from core.state_machine import ScreenTimeEngine, ScreenState, LastEvent

logger = logging.getLogger(__name__)

# Windows Constants
WTS_SESSION_LOCK = 0x7
WTS_SESSION_UNLOCK = 0x8
WM_WTSSESSION_CHANGE = 0x02B1


class SystemState(Enum):
    """System state enum"""
    ACTIVE = "active"
    IDLE = "idle"
    LOCKED = "locked"
    UNKNOWN = "unknown"


# High-confidence lock screen processes
LOCK_APPS = ["lockapp.exe", "logonui.exe"]


class StateAuthority:
    """
    Central gatekeeper for state transitions.
    Enforces rules like 'LOCKED is terminal' to prevent lower-confidence
    detectors (idle) from overriding higher-confidence ones (OS lock).
    """
    def __init__(self):
        self.current_state = SystemState.ACTIVE
        self.lock_source = None  # os | desktop | process | idle
        self._lock = threading.Lock()

    def can_transition(self, new_state: SystemState, source: str, remote_session_active: bool = False) -> bool:
        """Rule engine for state transitions"""
        if self.current_state == SystemState.LOCKED:
            # LOCKED can only be exited by:
            # 1. OS unlock event (highest authority)
            # 2. RDP override (user is active remotely)
            if new_state == SystemState.ACTIVE and (source == "os" or remote_session_active):
                return True
            return False
            
        return True

    def set_state(self, new_state: SystemState, source: str, remote_session_active: bool = False) -> bool:
        """Atomically update state if allowed"""
        with self._lock:
            if not self.can_transition(new_state, source, remote_session_active):
                return False
                
            self.current_state = new_state
            if new_state == SystemState.LOCKED:
                self.lock_source = source
            elif new_state == SystemState.ACTIVE:
                self.lock_source = None
            return True

    @property
    def state(self) -> SystemState:
        return self.current_state


class LASTINPUTINFO(Structure):
    """Structure for GetLastInputInfo"""
    _fields_ = [
        ('cbSize', c_uint),
        ('dwTime', c_uint)
    ]


class StateDetector:
    """
    Production-grade state detection
    - Uses WTSRegisterSessionNotification for lock/unlock
    - Uses GetLastInputInfo for idle detection
    """
    
    def __init__(self, 
                 idle_threshold_seconds: int = 120,
                 on_state_change: Optional[Callable] = None,
                 agent_id: str = None,
                 data_dir: Path = None):
        self.idle_threshold = idle_threshold_seconds
        self.on_state_change = on_state_change
        self.agent_id = agent_id or "unknown"
        
        self._hwnd = None
        self._thread = None
        self._running = False
        self.authority = StateAuthority()
        self._state_lock = threading.Lock()
        self._monitor_thread = None
        
        self._foreground_app = None
        
        # Centralized state machine (NEW ARCHITECTURE)
        self.current_state = "active"   # active | idle | locked
        self.idle_start_ts = None       # monotonic timestamp
        
        # ✅ NEW: Duration tracking
        self._last_state_change_time = time.time()  # Track time of last transition
        
        # ✅ NEW: Span generation
        self.pending_spans = []  # List of completed spans awaiting collection
        
        # ✅ NEW: Crash recovery
        import os
        if data_dir:
            self.state_file = Path(data_dir) / 'current_state.json'
        else:
            self.state_file = Path(os.path.expanduser('~')) / '.sentineledge' / 'current_state.json'
        
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
        except:
            pass
        
        # Link to collector for event emission
        self.collector = None
        
        # Reference to IdleDetector for synchronization (set by main.py)
        self.idle_detector = None
        
        # ✅ PHASE 2: Initialize state machine (ONLY place that calculates time)
        self.screen_time_engine = ScreenTimeEngine(
            data_dir=data_dir or Path(os.path.expanduser('~')) / '.sentineledge',
            agent_id=self.agent_id
        )
        
        # Check if pywin32 is available
        if not HAS_WIN32:
            logger.warning("[STATE] pywin32 not available - using fallback (always ACTIVE)")
            return
        
        # FIX #1: Detect initial lock state on startup
        if self._is_session_locked():
            self.authority.set_state(SystemState.LOCKED, source="desktop")
            logger.info("[STATE] Started in LOCKED state")
            self.current_state = "locked"
        else:
            logger.info("[STATE] Started in ACTIVE state")
            self.current_state = "active"
            
        # ✅ PHASE 2: Load persisted state and handle startup gap
        persisted = self.screen_time_engine.load_persisted_state()
        if persisted:
            gap_info = self.screen_time_engine.handle_startup(persisted)
            logger.info(f"[STATE] Startup gap handling: {gap_info}")
    
    def _is_session_locked(self) -> bool:
        """Check if workstation is locked OR fast user switched (no lock event)"""
        try:
            # Method 1: Check if desktop is accessible (locked/switched = inaccessible)
            hdesk = windll.user32.OpenInputDesktop(0, False, 0)
            if hdesk:
                windll.user32.CloseDesktop(hdesk)
                return False  # Desktop OK = unlocked/active
            return True  # No desktop = locked OR user switched
            
        except Exception:
            return True  # Assume locked on error
        
    def start(self):
        """Start detection"""
        if self._running:
            return
        
        # Skip if pywin32 not available
        if not HAS_WIN32:
            logger.warning("[STATE] Cannot start state detection without pywin32")
            self._running = True  # Mark as running to prevent repeated attempts
            return
        
        self._running = True
        
        # Start Windows event loop
        self._thread = threading.Thread(target=self._event_loop, daemon=True)
        self._thread.start()
        
        # Start idle monitoring
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()
        
        if self.idle_detector and self.authority.state == SystemState.LOCKED:
            try:
                # Standardized FIX 2: Startup lock sync
                self.idle_detector.set_locked(True)
                logger.info("[STATE] Synced IdleDetector to initial LOCKED state")
            except Exception as e:
                logger.error(f"[STATE] Failed to sync initial state: {e}")
        
        # New: Notify of initial state for timeline alignment
        if self.on_state_change:
            try:
                self.on_state_change(SystemState.UNKNOWN, self.authority.state, 0.0)  # ✅ duration=0 for initial state
                logger.debug(f"[STATE] Dispatched initial state notification: {self.authority.state.value}")
            except Exception as e:
                logger.error(f"[STATE] Initial notification callback error: {e}")
        
        logger.info("[STATE] Production state detector started")
    
    def stop(self):
        """Stop detection"""
        self._running = False
        if self._hwnd:
            try:
                win32gui.DestroyWindow(self._hwnd)
            except:
                pass
    
    def get_state(self) -> SystemState:
        """Get current state from authority"""
        return self.authority.state
        
    @property
    def is_locked(self) -> bool:
        """Authority check for locked state"""
        return self.authority.state == SystemState.LOCKED

    def _get_idle_seconds(self) -> float:
        """Standardized FIX 2: Single Windows idle clock authority"""
        try:
            lii = LASTINPUTINFO()
            lii.cbSize = sizeof(LASTINPUTINFO)
            if windll.user32.GetLastInputInfo(byref(lii)):
                tick = windll.kernel32.GetTickCount()
                millis = tick - lii.dwTime
                if millis < 0: # Tick overflow
                    millis += 2**32
                return max(0, millis / 1000.0)
            return 0.0
        except:
            return 0.0

    def _transition(self, new_state: str):
        """✅ PHASE 2: Use state machine for ALL time calculations"""
        prev_state = self.current_state
        if prev_state == new_state:
            return
        
        # ✅ Calculate duration in previous state (for span generation only)
        now = time.time()
        duration_seconds = now - self._last_state_change_time
        
        # ✅ NEW: CREATE SPAN for the exiting state (timeline visualization only)
        if self._last_state_change_time > 0 and duration_seconds >= 1.0:
            span = self._create_span(
                state=prev_state,
                start_time=self._last_state_change_time,
                end_time=now,
                duration=duration_seconds
            )
            if span:
                self.pending_spans.append(span)
        
        # ✅ PHASE 2: ONLY place time is calculated - call state machine
        # Map local state names to ScreenState enum
        state_map = {
            "active": ScreenState.ACTIVE,
            "idle": ScreenState.IDLE,
            "locked": ScreenState.LOCKED
        }
        
        if new_state in state_map:
            try:
                transition_info = self.screen_time_engine.transition(state_map[new_state])
                logger.debug(f"[STATE] State machine transition: {transition_info}")
            except Exception as e:
                logger.error(f"[STATE] State machine transition error: {e}", exc_info=True)
        
        self._last_state_change_time = now

        # SOLE AUTHORITY: Close idle and emit event exactly once
        if prev_state == "idle" and new_state in ("active", "locked"):
            if self.idle_detector:
                duration = self.idle_detector.complete_idle(time.time())
                if duration:
                    suffix = " (lock boundary)" if new_state == "locked" else ""
                    logger.info(f"Idle session completed: {duration:.1f}s{suffix}")
                    if self.collector and hasattr(self.collector, 'send_idle_event'):
                        try:
                            self.collector.send_idle_event(duration)
                        except Exception as e:
                            logger.error(f"[STATE] Error sending idle event: {e}")

        if new_state == "locked":
            if self.idle_detector:
                self.idle_detector.set_locked(True)

        if prev_state == "locked" and new_state == "active":
            if self.idle_detector:
                self.idle_detector.set_locked(False)

        # Mirror authority state locally
        self.current_state = new_state
        
        # Authority sync
        try:
            state_enum = SystemState(new_state)
            self.authority.set_state(state_enum, source="os")
        except:
            pass
        
        # ✅ NEW: Persist current state for crash recovery
        self._persist_current_state()
        
        # ✅ Call callback with duration
        if self.on_state_change:
            try:
                prev_state_enum = SystemState(prev_state) if prev_state != "unknown" else SystemState.UNKNOWN
                new_state_enum = SystemState(new_state)
                self.on_state_change(prev_state_enum, new_state_enum, duration_seconds)
            except Exception as e:
                logger.error(f"[STATE] Callback error: {e}", exc_info=True)
            
        logger.info(f"[STATE] {prev_state} -> {new_state}")

    def _handle_enter(self, prev_state, new_state):
        pass

    def _handle_exit(self, prev_state, new_state):
        pass

    def _event_loop(self):
        """Windows message loop for lock/unlock events"""
        try:
            # Create hidden window
            wc = win32gui.WNDCLASS()
            wc.lpfnWndProc = self._wnd_proc
            wc.lpszClassName = "SentinelStateDetector"
            wc.hInstance = win32api.GetModuleHandle(None)
            
            try:
                class_atom = win32gui.RegisterClass(wc)
            except Exception as e:
                if hasattr(e, 'winerror') and e.winerror == winerror.ERROR_CLASS_ALREADY_EXISTS:
                    class_atom = win32gui.RegisterClass(wc)
                else:
                    raise
            
            self._hwnd = win32gui.CreateWindow(
                class_atom, "SentinelStateDetector",
                0, 0, 0, 0, 0, 0, 0, wc.hInstance, None
            )
            
            # Register for session notifications
            WTSRegisterSessionNotification = ctypes.windll.wtsapi32.WTSRegisterSessionNotification
            result = WTSRegisterSessionNotification(self._hwnd, 0)
            
            if result:
                logger.info("[STATE] Registered for lock/unlock events")
            
            # Message pump
            import time
            while self._running:
                try:
                    win32gui.PumpWaitingMessages()
                except:
                    pass
                time.sleep(0.1)
                
        except Exception as e:
            logger.error(f"[STATE] Event loop error: {e}", exc_info=True)
    
    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        """Handle Windows messages"""
        if msg == WM_WTSSESSION_CHANGE:
            if wparam == WTS_SESSION_LOCK:
                logger.info("[STATE] Screen LOCKED (OS Event)")
                self._transition("locked")
                
            elif wparam == WTS_SESSION_UNLOCK:
                logger.info("[STATE] Screen UNLOCKED (OS Event)")
                self._transition("active")
        
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)
    
    def _monitor_loop(self):
        """Monitor idle time"""
        import time
        while self._running:
            try:
                self._update_state()
            except Exception as e:
                logger.error(f"[STATE] Monitor error: {e}")
            time.sleep(5)
    
    
    def _is_remote_session(self) -> bool:
        """FIX #6: Check if current session is a remote desktop session"""
        try:
            # Method 1: Check GetSystemMetrics for remote session
            SM_REMOTESESSION = 0x1000
            is_remote = windll.user32.GetSystemMetrics(SM_REMOTESESSION) != 0
            if is_remote:
                logger.debug("[STATE] Remote session detected via GetSystemMetrics")
                return True
            
            # Method 2: Check session ID (0xFFFFFFFF = no console = remote)
            try:
                import win32ts
                session_id = win32ts.WTSGetActiveConsoleSessionId()
                if session_id == 0xFFFFFFFF:
                    logger.debug("[STATE] Remote session detected via WTS")
                    return True
            except ImportError:
                pass  # win32ts not available
            except Exception:
                pass
            
            return False
        except Exception as e:
            logger.debug(f"[STATE] Could not detect remote session: {e}")
            return False  # Assume console session
    
    def _update_state(self):
        """Standardized FIX 2: Drive transitions using single clock"""
        if self._is_session_locked() and not self._is_remote_session():
            self._transition("locked")
            return

        if self.authority.state == SystemState.LOCKED:
            return

        # Centralized Timing (SOLE Authority)
        now = time.time()
        idle_for = self._get_idle_seconds()
        
        if self.idle_detector:
            # Centralized Timing (SOLE Authority)
            now = time.time()
            idle_for = self._get_idle_seconds()
            
            # Drive the idle engine exactly once per tick
            self.idle_detector.update(now - idle_for, now)
            
            if self.idle_detector.is_idle():
                self._transition("idle")
            else:
                self._transition("active")
        else:
            self._transition("active")

    # ========================================================================
    # SPAN GENERATION
    # ========================================================================

    def _create_span(self, state: str, start_time: float, end_time: float, duration: float) -> Optional[dict]:
        """
        Create an immutable span record with clock drift detection.
        Ensures timestamp consistency by adjusting end_time when capping duration.
        """
        try:
            from datetime import datetime, timezone
            
            # Calculate duration from timestamps (source of truth)
            calculated_duration = end_time - start_time
            
            # Detect suspicious clock jumps
            drift = abs(calculated_duration - duration)
            
            if drift > 5.0:  # More than 5 second drift
                logger.warning(
                    f"[SPAN] Clock drift detected: {drift:.1f}s "
                    f"(calculated={calculated_duration:.1f}s, measured={duration:.1f}s)"
                )
                # Use calculated duration as source of truth
                duration = calculated_duration
            
            # Validate duration range
            if duration < 1.0:
                return None
            
            # Cap duration AND adjust end_time to maintain consistency
            if duration > 86400:  # 24 hours
                logger.warning(f"[SPAN] Capping span >24h: {duration:.1f}s -> 86400s")
                duration = 86400
                end_time = start_time + 86400  # Adjust end_time to match capped duration
            
            start_dt = datetime.fromtimestamp(start_time, tz=timezone.utc)
            end_dt = datetime.fromtimestamp(end_time, tz=timezone.utc)
            
            # Idempotency key: deterministic, collision-free
            span_id = f"{self.agent_id}-{state}-{int(start_time * 1000)}"
            
            return {
                'span_id': span_id,
                'state': state,
                'start_time': start_dt.isoformat(),
                'end_time': end_dt.isoformat(),
                'duration_seconds': int(duration),
                'created_at': datetime.now(timezone.utc).isoformat()
            }
        except Exception as e:
            logger.error(f"[SPAN] Failed to create span: {e}")
            return None

    def get_pending_spans(self) -> list:
        """Return and clear pending spans (called by Collector)."""
        with self._state_lock:
            spans = self.pending_spans.copy()
            self.pending_spans.clear()
            return spans

    # ========================================================================
    # CRASH RECOVERY
    # ========================================================================

    def _load_persisted_state(self):
        """Recover in-progress session on startup."""
        try:
            import json
            if not self.state_file.exists():
                return
            
            with open(self.state_file, 'r') as f:
                data = json.load(f)
            
            # 1. Recover Current Session Span
            if 'current_state' in data and 'session_start' in data:
                prev_state = data['current_state']
                session_start = float(data['session_start'])
                now = time.time()
                
                duration = now - session_start
                
                # Cap recovery duration to 8 hours (reasonable max for unattended session)
                MAX_RECOVERY_DURATION = 8 * 3600  # 8 hours
                
                if duration > MAX_RECOVERY_DURATION:
                    logger.warning(
                        f"[RECOVERY] Interrupted session too long ({duration:.1f}s), "
                        f"capping to {MAX_RECOVERY_DURATION}s"
                    )
                    duration = MAX_RECOVERY_DURATION
                    # Adjust start time to match capped duration
                    session_start = now - MAX_RECOVERY_DURATION
                
                if duration > 60:  # Only if > 1 minute
                    # Create span for the interrupted session
                    span = self._create_span(
                        state=prev_state,
                        start_time=session_start,
                        end_time=now,
                        duration=duration
                    )
                    if span:
                        with self._state_lock:
                            self.pending_spans.append(span)
                        logger.info(f"[RECOVERY] Recovered {prev_state} session: {duration:.1f}s")
        except Exception as e:
            logger.error(f"[RECOVERY] Failed to load state: {e}")
        except Exception as e:
            logger.error(f"[RECOVERY] Failed to load state: {e}")

    def _persist_current_state(self):
        """Save current session metadata for crash recovery."""
        try:
            import json
            data = {
                'current_state': self.current_state,
                'session_start': self._last_state_change_time,
                'date': datetime.now().date().isoformat(),
                'timestamp': time.time()
            }
            with open(self.state_file, 'w') as f:
                json.dump(data, f)
        except Exception as e:
            logger.error(f"[STATE] Failed to persist state: {e}")
    
    # ========================================================================
    # CUMULATIVE TIME TRACKING (for heartbeat deltas)
    # ========================================================================
    
    def get_cumulative_deltas(self) -> dict:
        """
        ✅ PHASE 2: Read totals from state machine (ONLY source of truth)
        Also calls tick() to prevent time freezing.
        """
        # ✅ CRITICAL: Call tick() to update time for current state
        # This prevents the "time freeze" bug when no transitions occur
        try:
            self.screen_time_engine.tick()
        except Exception as e:
            logger.error(f"[STATE] State machine tick error: {e}", exc_info=True)
        
        # ✅ PHASE 2: Read totals from state machine (ONLY place that calculates time)
        try:
            totals = self.screen_time_engine.get_daily_totals()
            
            # Return in expected format for heartbeat
            return {
                'delta_active_seconds': totals.get('active_seconds', 0),
                'delta_idle_seconds': totals.get('idle_seconds', 0),
                'delta_locked_seconds': totals.get('locked_seconds', 0),
                'delta_away_seconds': totals.get('away_seconds', 0)  # NEW: track away time
            }
        except Exception as e:
            logger.error(f"[STATE] Error reading state machine totals: {e}", exc_info=True)
            return {
                'delta_active_seconds': 0,
                'delta_idle_seconds': 0,
                'delta_locked_seconds': 0,
                'delta_away_seconds': 0
            }
    
    def reset_cumulative(self):
        """✅ PHASE 2: Reset via state machine (ONLY place that manages counters)"""
        try:
            self.screen_time_engine.reset_daily()
            logger.info("[STATE] Daily counters reset via state machine")
        except Exception as e:
            logger.error(f"[STATE] Error resetting state machine: {e}", exc_info=True)

