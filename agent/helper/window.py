"""
Foreground Window Tracking Module - ENHANCED
=============================================
Tracks active foreground application and window with:
- Session-based tracking with accurate durations
- State persistence for recovery after restarts
- Brief app detection (catches quick switches)
- Friendly app name mapping
"""
import ctypes
from ctypes import wintypes
import os
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, List
import logging

# Import friendly name mapper
try:
    from .app_names import get_friendly_name, get_app_category, is_browser
except ImportError:
    # Fallback if module not available
    def get_friendly_name(exe_name): return exe_name
    def get_app_category(exe_name): return 'other'
    def is_browser(exe_name): return False

logger = logging.getLogger(__name__)


class WindowTracker:
    """
    Enhanced Window Tracker with:
    - Accurate session timing with sub-second precision
    - Brief app detection (apps used < 30s still counted)
    - Session persistence for restart recovery
    - App usage history for analytics
    """
    
    def __init__(self, capture_titles: bool = False, state_file: Path = None):
        self.capture_titles = capture_titles
        self._current_app = None
        self._current_title = None
        self._current_pid = None
        self._app_start = datetime.now(timezone.utc)
        
        # Enhanced tracking
        self._session_history: List[Dict] = []  # Recent app sessions
        self._cumulative_app_usage: Dict[str, float] = {}  # app_name -> total seconds
        self._brief_app_threshold = 5.0  # Apps used < 5s considered "brief"
        
        # Statistics
        self._total_switches = 0
        self._brief_switches = 0  # App switches < threshold
        
        # State persistence
        self._state_file = state_file or Path(r'C:\ProgramData\SentinelEdge\window_state.json')
        self.duration_lock = threading.Lock()  # Protect cumulative_app_usage updates
        
        # FIX: Initialize Windows APIs BEFORE _load_state() which may call _do_initial_sample()
        # This prevents "'WindowTracker' object has no attribute 'user32'" errors
        try:
            self.user32 = ctypes.windll.user32
            self.kernel32 = ctypes.windll.kernel32
            self.psapi = ctypes.windll.psapi
            self._win32_available = True
        except (AttributeError, OSError) as e:
            # Non-Windows or ctypes failure - set to None and handle gracefully
            logger.error(f"[WINDOW] Failed to load Windows APIs: {e}")
            self.user32 = None
            self.kernel32 = None
            self.psapi = None
            self._win32_available = False
        
        # Now safe to load state (which may call _do_initial_sample)
        self._load_state()
        
        # Initial sample to set current app (only if APIs available)
        if self._win32_available:
            self._do_initial_sample()
        
        logger.debug("[WINDOW] Enhanced WindowTracker initialized")
        
    def _load_state(self):
        """Load persisted state for session recovery AFTER RESTART"""
        try:
            if self._state_file and self._state_file.exists():
                with open(self._state_file, 'r') as f:
                    state = json.load(f)
                
                self._cumulative_app_usage = state.get('cumulative_app_usage', {})
                self._total_switches = state.get('total_switches', 0)
                self._session_history = state.get('session_history', [])
                
                # FIX #5: Restore CURRENT app session after restart
                last_app = state.get('last_app')
                last_start = state.get('last_app_start')  # ISO timestamp
                if last_app and last_start:
                    try:
                        restored_start = datetime.fromisoformat(last_start)
                        now = datetime.now(timezone.utc)
                        duration_since_restart = (now - restored_start).total_seconds()
                        
                        if duration_since_restart < 7200:  # Less than 2 hours = plausible
                            self._current_app = last_app
                            self._app_start = restored_start
                            logger.info(f"[WINDOW] Session restored: {last_app} (since {restored_start})")
                        else:
                            logger.warning(f"[WINDOW] Stale session skipped: {duration_since_restart/3600:.1f}h old")
                            self._do_initial_sample()
                    except Exception as e:
                        logger.warning(f"[WINDOW] Failed to restore session: {e}, fresh start")
                        self._do_initial_sample()
                else:
                    self._do_initial_sample()
                
                logger.debug(f"[WINDOW] Loaded state: {len(self._cumulative_app_usage)} apps tracked")
        except Exception as e:
            logger.warning(f"[WINDOW] Failed to load state: {e}")
            self._do_initial_sample()
    
    def _save_state(self):
        """Save state for persistence with session recovery info"""
        try:
            if self._state_file:
                state = {
                    'cumulative_app_usage': self._cumulative_app_usage,
                    'total_switches': self._total_switches,
                    'session_history': self._session_history[-50:],  # Save last 50 sessions
                    'last_app': self._current_app,
                    'last_update': datetime.now(timezone.utc).isoformat(),
                    # FIX #5: Add current session info for restart recovery
                    'last_app_start': self._app_start.isoformat() if self._app_start else None,
                    'last_pid': self._current_pid
                }
                # Atomic write
                temp_file = self._state_file.with_suffix('.tmp')
                temp_file.parent.mkdir(parents=True, exist_ok=True)
                with open(temp_file, 'w') as f:
                    json.dump(state, f, indent=2)
                temp_file.replace(self._state_file)
        except Exception as e:
            logger.warning(f"[WINDOW] Failed to save state: {e}")
    
    def _do_initial_sample(self):
        """Sample current window without recording a switch"""
        info = self.get_foreground_window_info()
        if info:
            self._current_app = info['app_name']
            self._current_title = info.get('window_title')
            self._current_pid = info.get('pid')
            self._app_start = datetime.now(timezone.utc)
            logger.debug(f"[WINDOW] Initial app: {self._current_app}")
        
    def update_settings(self, capture_titles: bool):
        """Update settings dynamically"""
        self.capture_titles = capture_titles
    
    def _get_window_with_timeout(self, timeout: float = 2) -> Optional[int]:
        """
        FIX #10: Get foreground window with timeout protection.
        If GetForegroundWindow() hangs, return None after timeout.
        """
        # Guard: Check if Windows APIs are available
        if not self._win32_available or not self.user32:
            return None
        
        result = [None]
        error = [None]

        def _get_window():
            try:
                result[0] = self.user32.GetForegroundWindow()
            except Exception as e:
                error[0] = e

        thread = threading.Thread(target=_get_window, daemon=True)
        thread.start()
        thread.join(timeout)

        if thread.is_alive():
            logger.error(
                f"[WINDOW] GetForegroundWindow() timeout after {timeout}s! "
                f"Possible system hang."
            )
            return None

        if error[0]:
            logger.error(f"[WINDOW] GetForegroundWindow() error: {error[0]}")
            return None

        return result[0]
        
    def get_foreground_window_info(self) -> Optional[Dict]:
        """Get foreground window process info"""
        try:
            # FIX #10: Use timeout-protected call for GetForegroundWindow
            hwnd = self._get_window_with_timeout(timeout=2)
            if not hwnd:
                return None
            
            # Get process ID
            pid = wintypes.DWORD()
            self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if not pid.value:
                return None
            
            # Get process handle
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            hprocess = self.kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION,
                False,
                pid.value
            )
            if not hprocess:
                return None
            
            try:
                # Get exe path
                exe_path = self._get_process_image_name(hprocess)
                if not exe_path:
                    return None
                
                # Get window title (ALWAYS for UWP detection, not just when capture_titles is on)
                title = self._get_window_title(hwnd)
                
                # Extract app name from path
                app_name = os.path.basename(exe_path).lower()
                
                # Detect UWP apps (Microsoft Store apps)
                if app_name == 'applicationframehost.exe' and title:
                    # Extract real app name from window title
                    uwp_app_name = self._extract_uwp_app_name(title)
                    if uwp_app_name:
                        logger.debug(f"[UWP] Detected: {uwp_app_name} (title: {title})")
                        app_name = uwp_app_name
                
                # Get friendly name for display
                friendly_name = get_friendly_name(app_name)
                category = get_app_category(app_name)
                browser_flag = is_browser(app_name)
                
                # Only include title if capture_titles is enabled
                display_title = title if self.capture_titles else None
                
                return {
                    'app_name': app_name,           # e.g., 'chrome.exe' or 'whatsapp.exe'
                    'friendly_name': friendly_name,  # e.g., 'Google Chrome' or 'WhatsApp'
                    'category': category,            # e.g., 'browser' or 'communication'
                    'is_browser': browser_flag,      # True/False
                    'exe_path': exe_path,
                    'window_title': display_title,
                    'pid': pid.value,
                    'hwnd': hwnd
                }
            finally:
                self.kernel32.CloseHandle(hprocess)
                
        except Exception as e:
            logger.debug(f"[WINDOW] Error getting foreground: {e}")
            return None
    
    def _get_process_image_name(self, hprocess) -> Optional[str]:
        """Get full process image path"""
        try:
            # QueryFullProcessImageName
            buf_size = wintypes.DWORD(4096)
            buf = ctypes.create_unicode_buffer(buf_size.value)
            
            if self.kernel32.QueryFullProcessImageNameW(
                hprocess, 0, buf, ctypes.byref(buf_size)
            ):
                return buf.value
        except Exception:
            pass
        return None
    
    def _get_window_title(self, hwnd) -> Optional[str]:
        """Get window title"""
        try:
            length = self.user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                self.user32.GetWindowTextW(hwnd, buf, length + 1)
                return buf.value
        except Exception:
            pass
        return None
    
    def _extract_uwp_app_name(self, window_title: str) -> Optional[str]:
        """
        Extract real app name from UWP window title.
        
        UWP apps in ApplicationFrameHost.exe show their name in the window title.
        Examples:
        - "WhatsApp" -> whatsapp.exe
        - "Calculator" -> calculator.exe
        - "Microsoft Store" -> store.exe
        - "Settings" -> systemsettings.exe
        """
        if not window_title:
            return None
        
        # Common UWP app mappings
        uwp_mappings = {
            'whatsapp': 'whatsapp.exe',
            'calculator': 'calculator.exe',
            'microsoft store': 'store.exe',
            'store': 'store.exe',
            'settings': 'systemsettings.exe',
            'mail': 'mail.exe',
            'calendar': 'calendar.exe',
            'photos': 'photos.exe',
            'movies & tv': 'movies.exe',
            'groove music': 'music.exe',
            'microsoft edge': 'msedge.exe',  # New Edge can run as UWP
            'xbox': 'xbox.exe',
            'xbox game bar': 'gamebar.exe',
            'skype': 'skype.exe',
            'onenote': 'onenote.exe',
            'feedback hub': 'feedback.exe',
            'microsoft teams': 'teams.exe',
            'spotify': 'spotify.exe',
            'netflix': 'netflix.exe',
            'weather': 'weather.exe',
            'clock': 'clock.exe',
            'alarms & clock': 'clock.exe',
            'snip & sketch': 'snip.exe',
            'sticky notes': 'stickynotes.exe',
            'your phone': 'yourphone.exe',
            'phone link': 'yourphone.exe',
        }
        
        # Extract first part of title (before " - " or other separators)
        title_parts = window_title.split(' - ')
        app_title = title_parts[0].strip().lower()
        
        # Check if we have a mapping
        if app_title in uwp_mappings:
            return uwp_mappings[app_title]
        
        # Check partial matches for compound names
        for key, value in uwp_mappings.items():
            if key in app_title or app_title in key:
                return value
        
        # Fallback: use sanitized title as app name
        # "WhatsApp" -> "whatsapp.exe"
        sanitized = ''.join(c for c in app_title if c.isalnum()).lower()
        if sanitized and len(sanitized) >= 2:
            return f"{sanitized}.exe"
        
        return None
    
    def sample(self) -> Optional[Dict]:
        """
        Sample current foreground window with enhanced tracking.
        
        Returns:
            dict with app info and duration if app changed, None if no change
        """
        now = datetime.now(timezone.utc)
        info = self.get_foreground_window_info()
        
        if not info:
            return None
        
        app_name = info['app_name']
        title = info.get('window_title')
        pid = info.get('pid')
        
        # Check if app changed (by name and PID to handle multiple instances)
        app_changed = app_name != self._current_app
        title_changed = self.capture_titles and title != self._current_title
        
        if app_changed or title_changed:
            # App/title changed - calculate duration of previous app
            duration = (now - self._app_start).total_seconds()
            
            # FIX #1: Handle clock changes (DST, manual adjustment)
            if duration < 0:
                logger.warning(f"[WINDOW] Clock went backwards ({duration:.1f}s), resetting app_start")
                self._app_start = now
                duration = 0
            
            # Cap maximum session duration to 24 hours (catches stuck sessions)
            elif duration > 86400:
                logger.warning(
                    f"WINDOW: App session exceeded 24h: {self._current_app}, "
                    f"duration={duration/3600:.1f}h, capping to 24h"
                )
                duration = 86400
            
            # Update cumulative usage for previous app
            if self._current_app and duration > 0:
                with self.duration_lock:
                    if self._current_app in self._cumulative_app_usage:
                        self._cumulative_app_usage[self._current_app] += duration
                    else:
                        self._cumulative_app_usage[self._current_app] = duration
            
            # Track statistics
            self._total_switches += 1
            if duration < self._brief_app_threshold:
                self._brief_switches += 1
            
            # Record session in history
            session = {
                'app_name': self._current_app,
                'window_title': self._current_title,
                'start': self._app_start.isoformat(),
                'end': now.isoformat(),
                'duration_seconds': duration,
                'is_brief': duration < self._brief_app_threshold
            }
            self._session_history.append(session)
            
            # Keep only last 100 sessions
            if len(self._session_history) > 100:
                self._session_history = self._session_history[-100:]
            
            result = {
                'app_name': self._current_app,
                'window_title': self._current_title,
                'duration_seconds': duration,
                'changed': True,
                'timestamp': now.isoformat(),
                'cumulative_seconds': self._cumulative_app_usage.get(self._current_app, 0),
                'is_brief': duration < self._brief_app_threshold,
                
                # New app info
                'new_app': app_name,
                'new_title': title
            }
            
            # Update current
            self._current_app = app_name
            self._current_title = title
            self._current_pid = pid
            self._app_start = now
            
            # Persist state periodically
            if self._total_switches % 10 == 0:  # Save every 10 switches
                self._save_state()
            
            logger.debug(f"[WINDOW] App switch: {result['app_name']} ({duration:.1f}s) -> {app_name}")
            
            return result
        
        # No change
        return None
    
    def get_current_app_duration(self) -> Dict:
        """Get duration of current app (for periodic snapshots)"""
        now = datetime.now(timezone.utc)
        duration = (now - self._app_start).total_seconds()
        
        # Get friendly name for current app
        friendly_name = get_friendly_name(self._current_app) if self._current_app else 'Unknown'
        category = get_app_category(self._current_app) if self._current_app else 'other'
        browser_flag = is_browser(self._current_app) if self._current_app else False
        
        with self.duration_lock:
            cumulative = self._cumulative_app_usage.get(self._current_app, 0) + duration
        
        return {
            'app_name': self._current_app,
            'friendly_name': friendly_name,      # Friendly name for display
            'category': category,                 # App category
            'is_browser': browser_flag,           # Is it a browser?
            'window_title': self._current_title,
            'duration_seconds': duration,
            'changed': False,
            'timestamp': now.isoformat(),
            'session_start': self._app_start.isoformat(),
            'cumulative_seconds': cumulative
        }
    
    def get_cumulative_usage(self) -> Dict[str, float]:
        """Get cumulative app usage for reporting"""
        # Include current app's ongoing duration
        result = dict(self._cumulative_app_usage)
        if self._current_app:
            now = datetime.now(timezone.utc)
            current_duration = (now - self._app_start).total_seconds()
            if self._current_app in result:
                result[self._current_app] += current_duration
            else:
                result[self._current_app] = current_duration
        return result
    
    def get_recent_sessions(self, count: int = 10) -> List[Dict]:
        """Get recent app sessions for debugging/display"""
        return self._session_history[-count:] if self._session_history else []
    
    def get_stats(self) -> Dict:
        """Get tracking statistics"""
        return {
            'total_switches': self._total_switches,
            'brief_switches': self._brief_switches,
            'current_app': self._current_app,
            'apps_tracked': len(self._cumulative_app_usage),
            'session_count': len(self._session_history)
        }
    
    def reset_cumulative(self):
        """Reset cumulative counters (call at end of reporting period)"""
        self._cumulative_app_usage.clear()
        self._session_history.clear()
        self._total_switches = 0
        self._brief_switches = 0
        self._save_state()
    
    def shutdown(self):
        """Clean shutdown - save final state"""
        # Record final app duration
        now = datetime.now(timezone.utc)
        if self._current_app:
            duration = (now - self._app_start).total_seconds()
            if duration > 0:
                with self.duration_lock:
                    if self._current_app in self._cumulative_app_usage:
                        self._cumulative_app_usage[self._current_app] += duration
                    else:
                        self._cumulative_app_usage[self._current_app] = duration
        
        self._save_state()
        logger.info(f"[WINDOW] Shutdown complete. Tracked {len(self._cumulative_app_usage)} apps, "
                   f"{self._total_switches} switches")
