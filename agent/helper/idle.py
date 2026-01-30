"""
Idle State Detection Module - DETECTION ONLY
==========================================
Minimalist module to detect whether the user is idle.
Timing and state management are handled by state_detector.py.
"""
import ctypes
import time
from ctypes import wintypes
from datetime import datetime, timezone
from typing import Literal, Dict, Optional, Callable
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
    - App-specific idle thresholds (CONFIGURABLE - can be disabled)
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
    #
    # NOTE: This can cause confusion during testing. If you test with VS Code,
    # Chrome, or Word open, the idle threshold will be 10-30 minutes instead of 5.
    # Set enable_app_specific_thresholds=False to disable this feature.
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
    
    def __init__(self, 
                 idle_threshold_seconds: int = 120, 
                 custom_thresholds: dict = None,
                 enable_app_specific_thresholds: bool = False,
                 on_idle_complete: Optional[Callable] = None):
        # Settings
        self.idle_threshold = idle_threshold_seconds
        self.enable_app_specific_thresholds = enable_app_specific_thresholds
        self.on_idle_complete = on_idle_complete
        
        # Windows API setup
        self.user32 = ctypes.windll.user32
        self.kernel32 = ctypes.windll.kernel32
        
        # State tracking (Standardized Fix 1)
        self.threshold = idle_threshold_seconds
        self._is_idle = False
        self.idle_start_ts = None
        self.is_locked = False
        self.last_input_ts = time.time()
        
        # EDGE CASE: Current foreground app for threshold lookup
        self._foreground_app = None
        self._custom_thresholds = {k.lower(): v for k, v in custom_thresholds.items()} if custom_thresholds else {}
        
        logger.info(f"[IDLE] IdleDetector initialized (Threshold: {self.idle_threshold}s)")

    def update(self, last_input_ts: float, now: float):
        """Standardized FIX 1: Idle update logic (Driven by StateDetector)"""
        if self.is_locked:
            return None

        idle_for = now - last_input_ts
        threshold = self.get_effective_threshold()

        # =====================================================================
        # TRANSITION: active -> idle
        # =====================================================================
        if not self._is_idle and idle_for >= threshold:
            self._is_idle = True
            self.idle_start_ts = now
            logger.info(f"[IDLE] Became idle (threshold: {threshold}s)")
            return "idle_start"

        # =====================================================================
        # TRANSITION: idle -> active (CRITICAL FIX - was missing!)
        # When user resumes activity, reset idle state
        # =====================================================================
        if self._is_idle and idle_for < threshold:
            duration = None
            if self.idle_start_ts:
                duration = now - self.idle_start_ts
                logger.info(f"[IDLE] Became active after {duration:.1f}s of idle")
            self._is_idle = False
            self.idle_start_ts = None
            return "idle_end"

        return None

    def complete_idle(self, now: float):
        """Standardized FIX 1: Clean idle completion (One Authority)"""
        if not self._is_idle or not self.idle_start_ts:
            return None

        duration = now - self.idle_start_ts
        self._is_idle = False
        self.idle_start_ts = None
        return duration

    def set_locked(self, locked: bool):
        """Standardized FIX 1: Lock awareness (NO Emission)"""
        self.is_locked = locked

        if locked:
            # Sync state but don't emit (StateDetector handles emission)
            self._is_idle = False
            self.idle_start_ts = None
        else:
            # reset activity baseline on unlock
            self.last_input_ts = time.time()

    def is_idle(self) -> bool:
        """Standardized FIX 1: Safe public getter"""
        return self._is_idle

    def reset_cumulative(self):
        """Standardized FIX 3: API Stub for DataCollector"""
        pass

    def update_settings(self, 
                       idle_threshold_seconds: int, 
                       custom_thresholds: dict = None,
                       enable_app_specific_thresholds: bool = None):
        """Standardized FIX 3: API Support for DataCollector"""
        self.idle_threshold = idle_threshold_seconds
        self.threshold = idle_threshold_seconds
        if custom_thresholds:
            self._custom_thresholds = {k.lower(): v for k, v in custom_thresholds.items()}
        if enable_app_specific_thresholds is not None:
            self.enable_app_specific_thresholds = enable_app_specific_thresholds
    
    def get_effective_threshold(self) -> int:
        """Threshold resolution logic"""
        if not self.enable_app_specific_thresholds:
            return self.idle_threshold
        
        if self._foreground_app:
            app_lower = self._foreground_app.lower()
            if app_lower in self._custom_thresholds:
                return self._custom_thresholds[app_lower]
            if app_lower in self.APP_SPECIFIC_THRESHOLDS:
                return self.APP_SPECIFIC_THRESHOLDS[app_lower]
        
        return self.idle_threshold

    def set_foreground_app(self, app_name: Optional[str]):
        """Update current foreground app"""
        self._foreground_app = app_name.lower() if app_name else None
