"""
Idle State Detection Module - ENHANCED
=======================================
Detects user idle/active/locked states using Windows APIs
Now with sub-second precision and state transition tracking
"""
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
from typing import Literal, Dict, Optional
import logging

IdleState = Literal['active', 'idle', 'locked']

logger = logging.getLogger(__name__)


class IdleDetector:
    """
    Enhanced Idle Detector with:
    - Sub-second precision for accurate time tracking
    - State transition history for analytics
    - Hysteresis to prevent rapid state flapping
    - Windows session event detection
    - App-specific idle thresholds (EDGE CASE FIX)
    """
    
    # =========================================================================
    # EDGE CASE FIX: App-Specific Idle Thresholds
    # =========================================================================
    # Different apps have different activity patterns:
    # - Media players: User watches passively (30 min threshold)
    # - Video conferencing: User listens/speaks (20 min threshold)
    # - Document readers: User reads (15 min threshold)
    # - Development tools: User thinks/debugs (10 min threshold)
    # - Default: Standard activity (5 min threshold)
    # =========================================================================
    
    APP_SPECIFIC_THRESHOLDS = {
        # Media Players - 30 minutes (1800 seconds)
        # User is watching content passively
        "vlc.exe": 1800,
        "vlc": 1800,
        "wmplayer.exe": 1800,
        "movies.exe": 1800,
        "video.ui.exe": 1800,  # Windows 11 Media Player
        "spotify.exe": 1800,
        "itunes.exe": 1800,
        "groove.exe": 1800,
        "musicbee.exe": 1800,
        "aimp.exe": 1800,
        "foobar2000.exe": 1800,
        "potplayermini64.exe": 1800,
        "potplayer.exe": 1800,
        "mpc-hc64.exe": 1800,
        "mpc-hc.exe": 1800,
        "mpv.exe": 1800,
        
        # Video Conferencing - 20 minutes (1200 seconds)
        # User is in a meeting (listening, speaking)
        "teams.exe": 1200,
        "msteams.exe": 1200,
        "ms-teams.exe": 1200,
        "zoom.exe": 1200,
        "zoom": 1200,
        "skype.exe": 1200,
        "webex.exe": 1200,
        "ciscowebex.exe": 1200,
        "slack.exe": 1200,
        "discord.exe": 1200,
        "gotomeeting.exe": 1200,
        "bluejeans.exe": 1200,
        
        # Document Readers - 15 minutes (900 seconds)
        # User is reading long-form content
        "acrobat.exe": 900,
        "acrord32.exe": 900,
        "foxitreader.exe": 900,
        "foxit reader.exe": 900,
        "sumatrapdf.exe": 900,
        "winword.exe": 900,  # Word in reading mode
        "excel.exe": 900,
        "powerpnt.exe": 900,
        "onenote.exe": 900,
        "kindle.exe": 900,
        "calibre.exe": 900,
        
        # Development Tools - 10 minutes (600 seconds)
        # User is debugging, thinking, reviewing code
        "devenv.exe": 600,  # Visual Studio
        "code.exe": 600,  # VS Code
        "idea64.exe": 600,  # IntelliJ IDEA
        "idea.exe": 600,
        "pycharm64.exe": 600,
        "pycharm.exe": 600,
        "webstorm64.exe": 600,
        "rider64.exe": 600,
        "android studio.exe": 600,
        "eclipse.exe": 600,
        "sublime_text.exe": 600,
        "atom.exe": 600,
        "notepad++.exe": 600,
        
        # Database Tools - 10 minutes (queries can run long)
        "ssms.exe": 600,  # SQL Server Management Studio
        "pgadmin4.exe": 600,
        "dbeaver.exe": 600,
        "mysql workbench.exe": 600,
        "datagrip64.exe": 600,
    }
    
    def __init__(self, idle_threshold_seconds: int = 300, custom_thresholds: dict = None):
        self.idle_threshold = idle_threshold_seconds
        self._last_state = 'active'
        self._state_start = datetime.now(timezone.utc)
        
        # Enhanced tracking
        self._last_input_ms = 0  # Last known input time
        self._state_transitions = []  # History of transitions (for analytics)
        self._transition_count = 0
        
        # Hysteresis settings (prevents rapid state changes)
        self._hysteresis_seconds = 5  # Must be in new state for 5s before accepting
        self._pending_state = None
        self._pending_state_start = None
        self._forced_state_recently = False  # Bypass hysteresis after force_state()
        
        # Cumulative counters (persist across samples)
        self._cumulative_active = 0.0
        self._cumulative_idle = 0.0
        self._cumulative_locked = 0.0
        self._last_sample_time = datetime.now(timezone.utc)
        
        # Session tracking
        self._session_start = datetime.now(timezone.utc)
        
        # FIX #3: Track date for midnight rollover detection
        self._last_date = datetime.now(timezone.utc).date()
        
        # EDGE CASE: Current foreground app for threshold lookup
        self._foreground_app = None
        
        # EDGE CASE: Custom thresholds from config (override defaults)
        self._custom_thresholds = {}
        if custom_thresholds:
            # Normalize keys to lowercase
            self._custom_thresholds = {k.lower(): v for k, v in custom_thresholds.items()}
            logger.info(f"[IDLE] Loaded {len(self._custom_thresholds)} custom app thresholds from config")
        
        # Windows API setup
        self.user32 = ctypes.windll.user32
        self.kernel32 = ctypes.windll.kernel32
        
        logger.debug("[IDLE] Enhanced IdleDetector initialized with app-specific thresholds")
        
    def update_settings(self, idle_threshold_seconds: int, custom_thresholds: dict = None):
        """Update settings dynamically"""
        self.idle_threshold = idle_threshold_seconds
        if custom_thresholds:
            self._custom_thresholds = {k.lower(): v for k, v in custom_thresholds.items()}
    
    def get_effective_threshold(self) -> int:
        """
        Get the effective idle threshold based on current foreground app.
        Priority: 1. Custom config thresholds, 2. Built-in app thresholds, 3. Default
        """
        if self._foreground_app:
            app_lower = self._foreground_app.lower()
            
            # Priority 1: Custom threshold from config
            if app_lower in self._custom_thresholds:
                threshold = self._custom_thresholds[app_lower]
                logger.debug(f"[IDLE] Using CUSTOM threshold for {app_lower}: {threshold}s")
                return threshold
            
            # Priority 2: Built-in app-specific threshold
            if app_lower in self.APP_SPECIFIC_THRESHOLDS:
                threshold = self.APP_SPECIFIC_THRESHOLDS[app_lower]
                logger.debug(f"[IDLE] Using built-in threshold for {app_lower}: {threshold}s")
                return threshold
        
        # Priority 3: Default threshold
        return self.idle_threshold
    
    def get_idle_seconds(self) -> float:
        """Get seconds since last input with sub-second precision"""
        try:
            class LASTINPUTINFO(ctypes.Structure):
                _fields_ = [
                    ('cbSize', wintypes.UINT),
                    ('dwTime', wintypes.DWORD)
                ]
            
            lii = LASTINPUTINFO()
            lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
            
            if self.user32.GetLastInputInfo(ctypes.byref(lii)):
                current_tick = self.kernel32.GetTickCount()
                # Handle tick count overflow (occurs every ~49.7 days)
                if current_tick < lii.dwTime:
                    elapsed_ms = (0xFFFFFFFF - lii.dwTime) + current_tick
                else:
                    elapsed_ms = current_tick - lii.dwTime
                self._last_input_ms = elapsed_ms
                return max(0, elapsed_ms / 1000.0)
            return 0.0
        except Exception as e:
            logger.error(f"[IDLE] Error getting idle time: {e}")
            return 0.0
        
    def get_last_input_time(self) -> int:
        """Legacy method - returns milliseconds since last input"""
        return int(self.get_idle_seconds() * 1000)
    
    def is_session_locked(self) -> bool:
        """Check if workstation is locked"""
        try:
            # OpenInputDesktop returns NULL if locked
            hdesk = self.user32.OpenInputDesktop(0, False, 0)
            if hdesk:
                self.user32.CloseDesktop(hdesk)
                return False
            return True
        except Exception:
            return False
    
    # =========================================================================
    # LOCK SCREEN APP FALLBACK DETECTION
    # =========================================================================
    # When pywin32 session detection fails, we can detect locked state by
    # checking if the foreground app is a known Windows lock screen process.
    # =========================================================================
    
    LOCK_SCREEN_APPS = {
        'lockapp.exe',           # Windows 10/11 Lock Screen
        'logonui.exe',           # Login UI
        'lockscreencontenthost.exe',  # Lock Screen Content Host
    }
    
    def set_foreground_app(self, app_name: str):
        """
        Set the current foreground app name for lock detection fallback.
        Called by collector before sampling idle state.
        """
        self._foreground_app = app_name.lower() if app_name else None
    
    def is_lock_screen_app(self) -> bool:
        """
        Check if current foreground app is a Windows lock screen app.
        Used as fallback when session lock detection fails.
        """
        if hasattr(self, '_foreground_app') and self._foreground_app:
            return self._foreground_app in self.LOCK_SCREEN_APPS
        return False
    
    def _detect_raw_state(self) -> IdleState:
        """Get raw current idle state without hysteresis"""
        # Method 1: Check session locked (via OpenInputDesktop - may fail without pywin32)
        if self.is_session_locked():
            return 'locked'
        
        # Method 2: FALLBACK - Check if foreground app is a lock screen app
        # This works even when pywin32 session detection fails
        if self.is_lock_screen_app():
            logger.debug("[IDLE] Lock detected via lockapp.exe fallback")
            return 'locked'
        
        # Check idle time using APP-SPECIFIC THRESHOLD
        idle_seconds = self.get_idle_seconds()
        effective_threshold = self.get_effective_threshold()
        
        if idle_seconds >= effective_threshold:
            return 'idle'
        return 'active'
    
    def get_current_state(self) -> IdleState:
        """Get current idle state with hysteresis"""
        # PRIORITY 1: Return forced state immediately (bypass hysteresis)
        if self._forced_state_recently:
            self._forced_state_recently = False
            logger.debug(f"[IDLE] Bypassing hysteresis for forced state: {self._last_state}")
            return self._last_state
        
        raw_state = self._detect_raw_state()
        now = datetime.now(timezone.utc)
        
        # If state matches current, clear pending
        if raw_state == self._last_state:
            self._pending_state = None
            self._pending_state_start = None
            return self._last_state
        
        # =====================================================================
        # BUG FIX: IMMEDIATE state transition FROM locked
        # When transitioning from locked → active/idle, accept immediately
        # because screen unlock is a confirmed user action (no hysteresis needed)
        # =====================================================================
        if self._last_state == 'locked' and raw_state in ['active', 'idle']:
            logger.info(f"[IDLE] Immediate unlock transition: locked → {raw_state}")
            self._pending_state = None
            self._pending_state_start = None
            return raw_state
        
        # New potential state change (with hysteresis for other transitions)
        if self._pending_state != raw_state:
            # Start tracking new potential state
            self._pending_state = raw_state
            self._pending_state_start = now
            return self._last_state  # Keep current until confirmed
        
        # Same pending state - check hysteresis timeout
        if self._pending_state_start:
            elapsed = (now - self._pending_state_start).total_seconds()
            if elapsed >= self._hysteresis_seconds:
                # Confirmed state change
                return raw_state
        
        return self._last_state
    
    def sample(self) -> Dict:
        """
        Sample current state with enhanced tracking.
        
        Returns:
            dict with:
            - state: current idle state
            - duration_seconds: time in previous state (if changed)
            - changed: whether state changed
            - idle_seconds: raw idle time from Windows
            - cumulative: cumulative time counters since session start
        """
        now = datetime.now(timezone.utc)
        current_date = now.date()
        current_state = self.get_current_state()
        
        # FIX #3: Detect midnight rollover
        if current_date != self._last_date:
            logger.info(
                f"[IDLE] Midnight rollover detected: "
                f"{self._last_date} → {current_date}"
            )
            logger.info(
                f"[IDLE] Final cumulative for {self._last_date}: "
                f"active={self._cumulative_active:.0f}s "
                f"idle={self._cumulative_idle:.0f}s "
                f"locked={self._cumulative_locked:.0f}s"
            )
            
            # Reset cumulative for new day
            self._cumulative_active = 0.0
            self._cumulative_idle = 0.0
            self._cumulative_locked = 0.0
            self._session_start = now
            self._last_date = current_date
            self._last_sample_time = now
            
            logger.info(f"[IDLE] Cumulative counters reset for new day: {current_date}")
        
        # Calculate time since last sample
        time_delta = (now - self._last_sample_time).total_seconds()
        self._last_sample_time = now
        
        # FIX #4: Detect clock going backwards (DST, manual time change)
        if time_delta < 0:
            logger.error(
                f"[IDLE] Clock went BACKWARDS: {time_delta:.0f}s "
                f"(DST or manual time change?)"
            )
            logger.warning("[IDLE] Skipping this sample to avoid negative time")
            
            return {
                'state': current_state,
                'duration_seconds': 0,
                'changed': False,
                'timestamp': now.isoformat(),
                'idle_seconds': self.get_idle_seconds(),
                'time_in_state': (now - self._state_start).total_seconds(),
                'cumulative': self.get_cumulative_times()
            }
        
        # FIX #2: Detect hibernate/sleep (time gap > 1 hour)
        SLEEP_DETECTION_THRESHOLD = 3600  # 1 hour
        if time_delta > SLEEP_DETECTION_THRESHOLD:
            logger.warning(
                f"[IDLE] Large time gap: {time_delta:.0f}s ({time_delta/3600:.1f}h) - "
                f"sleep/hibernate detected"
            )
            
            logger.info(
                f"[IDLE] Pre-sleep cumulative: "
                f"active={self._cumulative_active:.0f}s "
                f"idle={self._cumulative_idle:.0f}s "
                f"locked={self._cumulative_locked:.0f}s"
            )
            
            # Reset for new session after wake - don't add sleep time
            self._cumulative_active = 0.0
            self._cumulative_idle = 0.0
            self._cumulative_locked = 0.0
            self._session_start = now
            
            logger.info("[IDLE] Session reset after sleep/hibernate")
            
            return {
                'state': current_state,
                'duration_seconds': 0,
                'changed': False,
                'timestamp': now.isoformat(),
                'idle_seconds': self.get_idle_seconds(),
                'time_in_state': 0,
                'cumulative': {
                    'active_seconds': 0.0,
                    'idle_seconds': 0.0,
                    'locked_seconds': 0.0,
                    'session_start': self._session_start.isoformat()
                }
            }
        
        # Update cumulative counters based on PREVIOUS state (before any change)
        if self._last_state == 'active':
            self._cumulative_active += time_delta
        elif self._last_state == 'idle':
            self._cumulative_idle += time_delta
        elif self._last_state == 'locked':
            self._cumulative_locked += time_delta
        
        changed = current_state != self._last_state
        duration = (now - self._state_start).total_seconds() if changed else 0
        
        result = {
            'state': current_state,
            'duration_seconds': duration,
            'changed': changed,
            'timestamp': now.isoformat(),
            
            # Enhanced data
            'idle_seconds': self.get_idle_seconds(),
            'time_in_state': (now - self._state_start).total_seconds(),
            
            # Cumulative counters (for accurate screen time)
            'cumulative': {
                'active_seconds': self._cumulative_active,
                'idle_seconds': self._cumulative_idle,
                'locked_seconds': self._cumulative_locked,
                'session_start': self._session_start.isoformat()
            }
        }
        
        # Handle state transition
        if changed:
            # Record transition
            self._transition_count += 1
            transition_record = {
                'from_state': self._last_state,
                'to_state': current_state,
                'timestamp': now.isoformat(),
                'duration_in_previous': duration
            }
            self._state_transitions.append(transition_record)
            
            # Keep only last 100 transitions
            if len(self._state_transitions) > 100:
                self._state_transitions = self._state_transitions[-100:]
            
            # Update state tracking
            self._last_state = current_state
            self._state_start = now
            self._pending_state = None
            self._pending_state_start = None
            
            logger.debug(f"[IDLE] State: {transition_record['from_state']} -> {current_state} "
                        f"(after {duration:.1f}s)")
        
        return result
    
    def get_cumulative_times(self) -> Dict:
        """Get cumulative time counters for screen time reporting"""
        return {
            'active_seconds': self._cumulative_active,
            'idle_seconds': self._cumulative_idle,
            'locked_seconds': self._cumulative_locked,
            'session_start': self._session_start.isoformat(),
            'transition_count': self._transition_count
        }
    
    def force_state(self, state: IdleState):
        """
        Force idle detector to a specific state.
        Called by StateDetector when it detects lock/unlock via Windows events.
        This ensures IdleDetector stays synchronized with system state.
        """
        now = datetime.now(timezone.utc)

        # Only force if state is actually changing
        if state == self._last_state:
            return

        # Calculate time since last sample
        time_delta = (now - self._last_sample_time).total_seconds()
        self._last_sample_time = now

        # FIX #4: Check for negative time delta (DST, clock change)
        if time_delta < 0:
            logger.error(f"[IDLE] force_state() - Clock went backwards: {time_delta:.0f}s")
            time_delta = 0  # Don't add negative time
        
        # FIX #2: Check for sleep/hibernate - Enhanced with early return
        # FIX #3: Reduced threshold to catch shorter sleep cycles (30 min instead of 1 hour)
        SLEEP_DETECTION_THRESHOLD = 1800  # 30 minutes (catches short naps)
        if time_delta > SLEEP_DETECTION_THRESHOLD:
            logger.warning(f"[IDLE] Large time gap detected: {time_delta:.0f}s ({time_delta/3600:.1f}h) - sleep/wake event")
            logger.info(f"[IDLE] Pre-wake cumulative: active={self._cumulative_active:.0f}s idle={self._cumulative_idle:.0f}s locked={self._cumulative_locked:.0f}s")
            
            # Reset counters, don't add sleep time
            self._cumulative_active = 0.0
            self._cumulative_idle = 0.0
            self._cumulative_locked = 0.0
            self._session_start = now
            self._last_sample_time = now
            
            logger.info("[IDLE] Session reset after sleep/wake")
            
            # Force new state and return early (skip normal time accumulation)
            self._last_state = state
            self._state_start = now
            self._pending_state = None
            self._pending_state_start = None
            logger.info(f"[IDLE] State forced to: {state} (after sleep/wake)")
            return

        # Update cumulative counter for PREVIOUS state
        if self._last_state == 'active':
            self._cumulative_active += time_delta
        elif self._last_state == 'idle':
            self._cumulative_idle += time_delta
        elif self._last_state == 'locked':
            self._cumulative_locked += time_delta

        # Record transition
        self._transition_count += 1
        transition_record = {
            'from_state': self._last_state,
            'to_state': state,
            'timestamp': now.isoformat(),
            'forced': True
        }
        self._state_transitions.append(transition_record)
        
        # Keep only last 100 transitions
        if len(self._state_transitions) > 100:
            self._state_transitions = self._state_transitions[-100:]

        # CRITICAL: Update state BEFORE clearing hysteresis
        old_state = self._last_state
        self._last_state = state
        self._state_start = now
        
        # Clear hysteresis timers
        self._pending_state = None
        self._pending_state_start = None
        
        # Set flag to bypass hysteresis on next get_current_state() call
        self._forced_state_recently = True

        logger.info(f"[IDLE] State forced: {old_state} → {state} (synced with StateDetector)")
    
    def reset_cumulative(self):
        """Reset cumulative counters (call at end of reporting period)"""
        self._cumulative_active = 0.0
        self._cumulative_idle = 0.0
        self._cumulative_locked = 0.0
        self._session_start = datetime.now(timezone.utc)
        self._transition_count = 0
        self._state_transitions.clear()
    
    def get_state_info(self) -> Dict:
        """Get full state info for persistence/debugging"""
        return {
            'current_state': self._last_state,
            'state_start': self._state_start.isoformat(),
            'cumulative': self.get_cumulative_times(),
            'idle_threshold': self.idle_threshold,
            'last_transitions': self._state_transitions[-10:] if self._state_transitions else []
        }
