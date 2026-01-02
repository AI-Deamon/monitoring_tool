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
import threading
import logging
from enum import Enum
from typing import Callable, Optional

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
                 idle_threshold_seconds: int = 300,
                 on_state_change: Optional[Callable] = None):
        self.idle_threshold = idle_threshold_seconds
        self.on_state_change = on_state_change
        
        self._current_state = SystemState.ACTIVE
        self._is_locked = False
        
        self._hwnd = None
        self._thread = None
        self._running = False
        self._state_lock = threading.Lock()
        self._monitor_thread = None
        
        # Reference to IdleDetector for synchronization (set by main.py)
        self.idle_detector = None
        
        # Check if pywin32 is available
        if not HAS_WIN32:
            logger.warning("[STATE] pywin32 not available - using fallback (always ACTIVE)")
            return
        
        # FIX #1: Detect initial lock state on startup
        if self._is_session_locked():
            self._is_locked = True
            self._current_state = SystemState.LOCKED
            logger.info("[STATE] Started in LOCKED state")
        else:
            logger.info("[STATE] Started in ACTIVE state")
    
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
        
        # FIX #1: Sync IdleDetector with initial state
        if self.idle_detector and self._is_locked:
            try:
                self.idle_detector.force_state('locked')
                logger.info("[STATE] Synced IdleDetector to initial LOCKED state")
            except Exception as e:
                logger.error(f"[STATE] Failed to sync initial state: {e}")
        
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
        """Get current state"""
        return self._current_state
    
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
                logger.info("[STATE] Screen LOCKED")
                with self._state_lock:
                    self._is_locked = True
                
                # Synchronize IdleDetector immediately
                if self.idle_detector:
                    try:
                        self.idle_detector.force_state('locked')
                    except Exception as e:
                        logger.error(f"[STATE] Failed to sync IdleDetector: {e}")
                
                self._update_state()
                
            elif wparam == WTS_SESSION_UNLOCK:
                logger.info("[STATE] Screen UNLOCKED")
                with self._state_lock:
                    self._is_locked = False
                
                # Synchronize IdleDetector immediately
                if self.idle_detector:
                    try:
                        self.idle_detector.force_state('active')
                    except Exception as e:
                        logger.error(f"[STATE] Failed to sync IdleDetector: {e}")
                
                self._update_state()
        
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
    
    def _get_idle_time(self) -> float:
        """Get seconds since last input"""
        try:
            lastInputInfo = LASTINPUTINFO()
            lastInputInfo.cbSize = sizeof(lastInputInfo)
            windll.user32.GetLastInputInfo(byref(lastInputInfo))
            millis = windll.kernel32.GetTickCount() - lastInputInfo.dwTime
            if millis < 0:
                millis += 2**32
            return millis / 1000.0
        except:
            return 0.0
    
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
        """Determine current state"""
        with self._state_lock:
            old_state = self._current_state
            
            # FIX #6: Check for Remote Desktop - don't report as locked if remote
            if self._is_locked and not self._is_remote_session():
                # Physical lock and not remote = truly locked
                new_state = SystemState.LOCKED
            elif self._is_locked and self._is_remote_session():
                # Physical lock but working remotely - treat as active/idle
                logger.debug("[STATE] Physical lock but remote session active")
                idle_seconds = self._get_idle_time()
                if idle_seconds >= self.idle_threshold:
                    new_state = SystemState.IDLE
                else:
                    new_state = SystemState.ACTIVE
            else:
                # Normal case - check idle time
                idle_seconds = self._get_idle_time()
                if idle_seconds >= self.idle_threshold:
                    new_state = SystemState.IDLE
                else:
                    new_state = SystemState.ACTIVE
            
            if new_state != old_state:
                logger.info(f"[STATE] {old_state.value} -> {new_state.value}")
                self._current_state = new_state
                
                if self.on_state_change:
                    try:
                        self.on_state_change(old_state, new_state)
                    except Exception as e:
                        logger.error(f"[STATE] Callback error: {e}")
