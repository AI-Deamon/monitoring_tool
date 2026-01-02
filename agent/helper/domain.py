"""
Domain Session Tracking Module - REDESIGNED v2.0
=================================================
Tracks active domain usage sessions (not just history extraction).

MAJOR FEATURES:
- CDP (Chrome DevTools Protocol) support for active tab detection
- Session-based duration tracking
- Works with Brave, Chrome, Edge (Chromium browsers)
- Multiple fallback strategies for reliability

Design Philosophy:
- Track domains like we track app usage (session-based)
- Works even when users keep tabs open for hours
- Does NOT rely solely on browser history
"""

import os
import re
import json
import sqlite3
import shutil
import tempfile
import ctypes
from ctypes import wintypes
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Optional, Tuple
from urllib.parse import urlparse
import logging
import urllib.request
import urllib.error
import ipaddress

logger = logging.getLogger(__name__)

# ============================================================================
#   ENHANCED DOMAIN EXTRACTION FUNCTIONS (Integrated from domain_extractor.py)
# ============================================================================

def extract_domain_from_url_enhanced(url: str, keep_www: Optional[bool] = None) -> Optional[str]:
    """
    Enhanced domain extraction with comprehensive edge case handling.
    
    Args:
        url: URL to extract domain from
        keep_www: None (auto-strip www), True (keep www), False (force strip www)
    
    Returns:
        Extracted domain or None
        
    Handles:
        - IP addresses (preserves as-is)
        - Port numbers (smart handling for localhost/IPs)
        - International domains (IDN encoding)
        - Special protocols (returns None)
        - Private IPs (preserves with port)
        - user:pass@ format
        - Protocol-relative URLs (//)
    """
    if not url:
        return None
    
    # Skip non-HTTP protocols
    if url.startswith(('about:', 'chrome:', 'edge:', 'file:', 'data:', 'javascript:', 'brave:', 'opera:', 'vivaldi:', 'arc:')):
        return None
    
    try:
        # Handle protocol-relative URLs
        if url.startswith('//'):
            url = 'https:' + url
        
        # Add scheme if missing
        elif not url.startswith(('http://', 'https://')):
            url = 'http://' + url
        
        parsed = urlparse(url)
        netloc = parsed.netloc
        
        if not netloc:
            return None
        
        # Handle user:pass@domain format
        if '@' in netloc:
            netloc = netloc.split('@')[1]
        
        # Handle port numbers
        if ':' in netloc:
            host, port = netloc.rsplit(':', 1)
            
            # Keep port for localhost and private IPs
            try:
                if _is_private_or_local(host):
                    netloc = netloc  # Keep with port
                elif port in ('80', '443'):
                    netloc = host  # Strip standard ports
                # else keep non-standard port
            except:
                pass
        
        # Check if it's an IP address
        try:
            ipaddress.ip_address(netloc.split(':')[0])
            return netloc.lower()  # Return IP as-is (lowercase for consistency)
        except ValueError:
            pass
        
        # Handle international domain names (IDN) - only apply if needed
        try:
            # Only apply IDN encoding if domain contains non-ASCII characters
            if any(ord(char) > 127 for char in netloc):
                netloc = netloc.encode('idna').decode('ascii')
        except Exception:
            pass
        
        # Handle www prefix based on parameter or auto-detect
        if keep_www is not None:
            # Explicit setting
            if not keep_www and netloc.startswith('www.'):
                netloc = netloc[4:]
        else:
            # Auto-detect: strip www for consistency (most common behavior)
            if netloc.startswith('www.'):
                netloc = netloc[4:]
        
        return netloc.lower()
    
    except Exception as e:
        logger.error(f"Enhanced domain extraction error: {e} for URL: {url}")
        return None


def _is_private_or_local(host: str) -> bool:
    """Check if host is localhost or private IP"""
    if host in ('localhost', '127.0.0.1', '::1'):
        return True
    
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private
    except ValueError:
        return False


def get_base_domain(domain: str) -> Optional[str]:
    """
    Extract base domain (remove subdomains).
    
    Examples:
        mail.google.com -> google.com
        api.github.com -> github.com
        192.168.1.1 -> 192.168.1.1 (IPs unchanged)
    """
    if not domain:
        return None
    
    # Skip IP addresses
    try:
        ipaddress.ip_address(domain.split(':')[0])
        return domain  # Return IP as-is
    except ValueError:
        pass
    
    parts = domain.split('.')
    if len(parts) >= 2:
        return '.'.join(parts[-2:])
    
    return domain


def is_subdomain(domain: str) -> bool:
    """Check if domain has subdomain (e.g., mail.google.com)"""
    if not domain:
        return False
    
    # Skip IPs
    try:
        ipaddress.ip_address(domain.split(':')[0])
        return False
    except:
        pass
    
    parts = domain.split('.')
    return len(parts) > 2

# ============================================================================
#   END OF ENHANCED EXTRACTION FUNCTIONS
# ============================================================================

# ============================================================================
#   BROWSER CONFIGURATIONS
# ============================================================================

BROWSER_CONFIGS = {
    'chrome': {
        'name': 'Google Chrome',
        'process_names': ['chrome.exe'],
        'title_suffix': ' - Google Chrome',
        'history_path': Path(os.environ.get('LOCALAPPDATA', '')) /
                        'Google/Chrome/User Data/Default/History',
        'cdp_port': 9222,
        'cdp_enabled': True,
    },
    'edge': {
        'name': 'Microsoft Edge',
        'process_names': ['msedge.exe'],
        'title_suffix': ' - Microsoft Edge',
        'history_path': Path(os.environ.get('LOCALAPPDATA', '')) /
                        'Microsoft/Edge/User Data/Default/History',
        'cdp_port': 9223,
        'cdp_enabled': True,
    },
    'brave': {
        'name': 'Brave',
        'process_names': ['brave.exe'],
        'title_suffix': ' - Brave',
        'history_path': Path(os.environ.get('LOCALAPPDATA', '')) /
                        'BraveSoftware/Brave-Browser/User Data/Default/History',
        'cdp_port': 9224,
        'cdp_enabled': True,
    },
    'firefox': {
        'name': 'Mozilla Firefox',
        'process_names': ['firefox.exe'],
        'title_suffix': ' — Mozilla Firefox',
        'alt_title_suffixes': [' - Mozilla Firefox', ' — Firefox'],
        'history_path': None,
        'cdp_port': 9229,
        'cdp_enabled': False,
    },
    'comet': {
        'name': 'Comet Browser',
        'process_names': ['comet.exe', 'cometbrowser.exe'],
        'title_suffix': ' - Comet',
        'history_path': Path(os.environ.get('LOCALAPPDATA', '')) /
                        'Comet/User Data/Default/History',
        'cdp_port': 9225,
        'cdp_enabled': True,
    },
    'arc': {
        'name': 'Arc Browser',
        'process_names': ['arc.exe'],
        'title_suffix': ' — Arc',
        'alt_title_suffixes': [' - Arc'],
        'history_path': Path(os.environ.get('LOCALAPPDATA', '')) /
                        'Arc/User Data/Default/History',
        'cdp_port': 9226,
        'cdp_enabled': True,
    },
    'opera': {
        'name': 'Opera',
        'process_names': ['opera.exe'],
        'title_suffix': ' - Opera',
        'history_path': Path(os.environ.get('APPDATA', '')) /
                        'Opera Software/Opera Stable/History',
        'cdp_port': 9227,
        'cdp_enabled': True,
    },
    'vivaldi': {
        'name': 'Vivaldi',
        'process_names': ['vivaldi.exe'],
        'title_suffix': ' - Vivaldi',
        'history_path': Path(os.environ.get('LOCALAPPDATA', '')) /
                        'Vivaldi/User Data/Default/History',
        'cdp_port': 9228,
        'cdp_enabled': True,
    },
}

# Common browser process names for quick detection
ALL_BROWSER_PROCESSES = [
    'chrome.exe', 'msedge.exe', 'brave.exe', 'firefox.exe',
    'comet.exe', 'cometbrowser.exe', 'arc.exe',
    'opera.exe', 'vivaldi.exe'
]

# Firefox profile paths for different OS
FIREFOX_PATHS = {
    'windows': [
        os.path.expandvars(r'%APPDATA%\Mozilla\Firefox\Profiles'),
        os.path.expandvars(r'%LOCALAPPDATA%\Mozilla\Firefox\Profiles')
    ],
    'linux': [
        os.path.expanduser('~/.mozilla/firefox'),
        os.path.expanduser('~/.var/app/org.mozilla.firefox/.mozilla/firefox')  # Flatpak
    ],
    'darwin': [  # macOS
        os.path.expanduser('~/Library/Application Support/Firefox/Profiles')
    ]
}


def get_firefox_profile_path() -> Optional[Path]:
    """
    Get Firefox profile path for the current OS.
    Returns the first valid profile directory found.
    """
    import platform
    system = platform.system().lower()
    
    if system == 'windows':
        paths = FIREFOX_PATHS['windows']
    elif system == 'linux':
        paths = FIREFOX_PATHS['linux']
    elif system == 'darwin':
        paths = FIREFOX_PATHS['darwin']
    else:
        logger.warning(f"Unsupported OS for Firefox: {system}")
        return None
    
    for base_path in paths:
        if os.path.exists(base_path):
            try:
                profiles = [d for d in os.listdir(base_path) 
                           if os.path.isdir(os.path.join(base_path, d))]
                
                # Prefer .default-release profile (most recent)
                for profile in profiles:
                    if 'default-release' in profile.lower():
                        profile_path = Path(base_path) / profile
                        logger.debug(f"[FIREFOX] Found profile: {profile_path}")
                        return profile_path
                
                # Fallback to any .default profile
                for profile in profiles:
                    if '.default' in profile.lower():
                        profile_path = Path(base_path) / profile
                        logger.debug(f"[FIREFOX] Using profile: {profile_path}")
                        return profile_path
                
                # Fallback to first profile
                if profiles:
                    profile_path = Path(base_path) / profiles[0]
                    logger.debug(f"[FIREFOX] Using first profile: {profile_path}")
                    return profile_path
                    
            except Exception as e:
                logger.debug(f"[FIREFOX] Error accessing profiles: {e}")
                continue
    
    logger.debug("[FIREFOX] No profile found")
    return None


class DomainSession:
    """Represents an active domain usage session"""
    
    def __init__(self, domain: str, browser: str, url: Optional[str] = None, 
                 title: Optional[str] = None, raw_window_title: Optional[str] = None):
        self.domain = domain
        self.browser = browser
        self.url = url
        self.title = title
        self.raw_window_title = raw_window_title  # Store original window title
        self.start_time = datetime.now(timezone.utc)
        self.end_time: Optional[datetime] = None
    
    def end(self) -> Dict:
        """End the session and return the session data"""
        self.end_time = datetime.now(timezone.utc)
        duration = (self.end_time - self.start_time).total_seconds()
        
        # Fix #8: Cap maximum domain session duration to 24 hours (catches stuck sessions)
        if duration > 86400:  # 24 hours in seconds
            logger.warning(
                f"DOMAIN: Session exceeded 24h: {self.domain}, "
                f"duration={duration/3600:.1f}h, capping to 24h"
            )
            duration = 86400
            from datetime import timedelta
            self.end_time = self.start_time + timedelta(seconds=86400)
        
        return {
            'domain': self.domain,
            'browser': self.browser,
            'url': self.url,
            'title': self.title,
            'raw_title': self.raw_window_title,  # Raw window title for server-side filtering
            'raw_url': self.url,                 # CDP URL if available
            'start': self.start_time.isoformat(),
            'end': self.end_time.isoformat(),
            'duration_seconds': round(duration, 2)
        }
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for state persistence"""
        return {
            'domain': self.domain,
            'browser': self.browser,
            'url': self.url,
            'title': self.title,
            'start': self.start_time.isoformat(),
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'DomainSession':
        """Create from persisted state"""
        session = cls(
            domain=data['domain'],
            browser=data['browser'],
            url=data.get('url'),
            title=data.get('title')
        )
        session.start_time = datetime.fromisoformat(data['start'].replace('Z', '+00:00'))
        return session


class CDPClient:
    """
    Chrome DevTools Protocol client for active tab detection.
    
    CDP is the ONLY reliable way to get the active tab URL from browsers.
    Browser history and window titles are unreliable for long-open tabs.
    """
    
    # Ports we try for each browser
    # Ports to try for CDP detection
    # Note: 9229 (Firefox) intentionally excluded since CDP disabled by default
    CDP_PORTS = [9222, 9223, 9224, 9225, 9226, 9227, 9228]
    
    def __init__(self):
        self._last_successful_port: Optional[int] = None
        self._cdp_available: Dict[int, bool] = {}
    
    def get_active_tab(self) -> Optional[Dict]:
        """
        Get the active browser tab via CDP (returns first valid tab).
        
        Returns:
            Dict with 'url', 'title', 'domain' or None if CDP unavailable
        """
        # Try last successful port first
        if self._last_successful_port:
            result = self._try_cdp_port(self._last_successful_port)
            if result:
                return result
        
        # Try all known ports
        for port in self.CDP_PORTS:
            if port == self._last_successful_port:
                continue
            result = self._try_cdp_port(port)
            if result:
                self._last_successful_port = port
                return result
        
        return None
    
    def get_tab_by_title(self, window_title: str) -> Optional[Dict]:
        """
        Find the CDP tab that matches the given window title.
        
        This is the KEY to accurate domain detection - we use the window title
        (which shows the focused tab) to find the matching CDP tab.
        
        Args:
            window_title: The title from the browser window (focused tab title)
            
        Returns:
            Dict with 'url', 'title', 'domain' or None if not found
        """
        if not window_title:
            return None
        
        # Get all tabs from all ports
        all_tabs = self._get_all_tabs()
        
        if not all_tabs:
            return None
        
        # Normalize the window title for comparison
        window_title_lower = window_title.lower().strip()
        
        # Try to find an exact or close match
        best_match = None
        best_score = 0
        
        for tab in all_tabs:
            tab_title = tab.get('title', '').lower().strip()
            
            # Exact match
            if tab_title == window_title_lower:
                logger.debug(f"[CDP] Exact title match: {tab['domain']}")
                return tab
            
            # Title starts with same text (common when browser appends " - Browser Name")
            if window_title_lower.startswith(tab_title) or tab_title.startswith(window_title_lower):
                score = len(tab_title)
                if score > best_score:
                    best_score = score
                    best_match = tab
            
            # Partial match - title contains window title or vice versa
            elif window_title_lower in tab_title or tab_title in window_title_lower:
                score = min(len(tab_title), len(window_title_lower))
                if score > best_score:
                    best_score = score
                    best_match = tab
        
        if best_match:
            logger.debug(f"[CDP] Best title match: {best_match['domain']} (score={best_score})")
            return best_match
        
        return None
    
    def _get_all_tabs(self) -> List[Dict]:
        """Get all valid tabs from all CDP ports"""
        all_tabs = []
        
        for port in self.CDP_PORTS:
            tabs = self._get_tabs_from_port(port)
            all_tabs.extend(tabs)
        
        return all_tabs
    
    def _get_tabs_from_port(self, port: int) -> List[Dict]:
        """Get all valid page tabs from a CDP port"""
        try:
            url = f"http://127.0.0.1:{port}/json"
            req = urllib.request.Request(url, method='GET')
            req.add_header('Accept', 'application/json')
            
            with urllib.request.urlopen(req, timeout=0.5) as response:
                data = json.loads(response.read().decode('utf-8'))
                
                tabs = []
                for entry in data:
                    if entry.get('type') != 'page':
                        continue
                    
                    tab_url = entry.get('url', '')
                    tab_title = entry.get('title', '')
                    
                    # Skip internal browser pages
                    if any(tab_url.startswith(prefix) for prefix in [
                        'chrome://', 'edge://', 'brave://', 'about:',
                        'chrome-extension://', 'devtools://'
                    ]):
                        continue
                    
                    domain = self._extract_domain(tab_url)
                    
                    if domain:
                        tabs.append({
                            'url': tab_url,
                            'title': tab_title,
                            'domain': domain
                        })
                
                return tabs
                
        except:
            return []
    
    def _try_cdp_port(self, port: int) -> Optional[Dict]:
        """Try to get active tab from a CDP port"""
        
        # Skip Firefox port (CDP not enabled by default in Firefox)
        if port == 9229:
            return None
        
        try:
            url = f"http://127.0.0.1:{port}/json"
            req = urllib.request.Request(url, method='GET')
            req.add_header('Accept', 'application/json')
            
            with urllib.request.urlopen(req, timeout=0.5) as response:
                data = json.loads(response.read().decode('utf-8'))
                
                # CDP returns all tabs - we need to find the ACTIVE one
                # The active tab is typically the one with webSocketDebuggerUrl present
                # and is NOT a devtools or extension page
                
                valid_pages = []
                for entry in data:
                    if entry.get('type') != 'page':
                        continue
                    
                    tab_url = entry.get('url', '')
                    tab_title = entry.get('title', '')
                    
                    # Skip internal browser pages
                    if tab_url.startswith('chrome://') or tab_url.startswith('edge://'):
                        continue
                    if tab_url.startswith('brave://') or tab_url.startswith('about:'):
                        continue
                    if tab_url.startswith('chrome-extension://'):
                        continue
                    if tab_url.startswith('devtools://'):
                        continue
                    
                    # Extract domain
                    domain = self._extract_domain(tab_url)
                    
                    if domain:
                        valid_pages.append({
                            'url': tab_url,
                            'title': tab_title,
                            'domain': domain,
                            'id': entry.get('id', ''),
                            # Tabs with webSocketDebuggerUrl are more likely to be active
                            'has_debugger': bool(entry.get('webSocketDebuggerUrl'))
                        })
                
                if not valid_pages:
                    return None
                
                # Try to find the actually focused tab with better heuristics
                active_tab = None
                
                # Heuristic 1: Prefer non-localhost tabs (filter out dashboard)
                non_localhost_tabs = [tab for tab in valid_pages if tab['domain'] != 'localhost']
                if non_localhost_tabs:
                    active_tab = non_localhost_tabs[0]
                    logger.debug(f"[CDP] Selected non-localhost tab: {active_tab['domain']}")
                
                # Heuristic 2: Fall back to first tab if all are localhost
                if not active_tab and valid_pages:
                    active_tab = valid_pages[0]
                    logger.debug(f"[CDP] Using first tab (all localhost): {active_tab['domain']}")
                
                # Debug: Log all available tabs
                tab_list = [f"{tab['domain']} ({tab['title'][:20]}...)" for tab in valid_pages]
                logger.debug(f"[CDP] Available tabs: {tab_list}")
                logger.info(f"[CDP] Active tab: {active_tab['domain']} ({active_tab['title'][:30]}...)")
                return {
                    'url': active_tab['url'],
                    'title': active_tab['title'],
                    'domain': active_tab['domain']
                }
                
        except urllib.error.URLError:
            return None
        except Exception as e:
            logger.debug(f"[CDP] Port {port} error: {e}")
            return None
            return None
    
    def _extract_domain(self, url: str) -> Optional[str]:
        """
        Extract domain from URL using enhanced extraction.
        
        Uses extract_domain_from_url_enhanced() for comprehensive edge case handling:
        - IP addresses, ports for localhost, special protocols, IDN domains
        """
        return extract_domain_from_url_enhanced(url, keep_www=False)


class ActiveDomainTracker:
    """
    Tracks active domain usage in real-time.
    
    Detection Strategy (in order of reliability):
    1. CDP (Chrome DevTools Protocol) - BEST, always accurate
    2. Parse window title + lookup in history DB
    3. Extract domain from title heuristically
    4. Use sanitized title as pseudo-domain
    
    This approach:
    - Never locks browser DB files (uses temp copies)
    - Works with any Chromium browser
    - Handles long-running tabs without history entries
    """
    
    def __init__(self, capture_full_urls: bool = False):
        self.capture_full_urls = capture_full_urls
        
        # CDP client for active tab detection
        self._cdp_client = CDPClient()
        
        # Current active session
        self._current_session: Optional[DomainSession] = None
        
        # Completed sessions waiting to be sent
        self._pending_sessions: List[Dict] = []
        
        # Browser history last visit times (for incremental reads)
        self._last_visit_times: Dict[str, int] = {}
        
        # Title to URL cache (recent lookups)
        self._title_url_cache: Dict[str, Tuple[str, str]] = {}  # title -> (url, domain)
        self._cache_max_size = 100
        
        # Windows APIs
        self.user32 = ctypes.windll.user32
        self.kernel32 = ctypes.windll.kernel32
        
        # Track last known browser (for session end detection)
        self._last_browser: Optional[str] = None
        
        # Track when domain tracking is active
        self._tracking_active = False
        
        logger.info("[DOMAIN] ActiveDomainTracker initialized (CDP + History + Title fallback)")
        
        # Add this at the end of __init__ after self._tracking_active = False
        self.cleanup_orphaned_sessions()
    
    def cleanup_orphaned_sessions(self):
        """Clean up orphaned sessions from previous crashes."""
        # Use correct attribute: self._current_session instead of self.current_domain
        if not self._current_session:
            return
        
        try:
            from datetime import timedelta
            now = datetime.now(timezone.utc)
            
            # If current session is older than 2 hours, it's orphaned
            session_start = self._current_session.start_time
            if session_start:
                session_age = (now - session_start).total_seconds()
                if session_age > 7200:  # 2 hours
                    logger.warning(
                        f"CLEANUP: Found orphaned domain session: {self._current_session.domain}, "
                        f"age={session_age/3600:.1f}h, force-ending"
                    )
                    
                    # End the orphaned session with capped duration
                    # Force end time to be 2 hours after start (max reasonable session)
                    self._current_session.end_time = session_start + timedelta(seconds=7200)
                    ended_session = {
                        'domain': self._current_session.domain,
                        'browser': self._current_session.browser,
                        'url': self._current_session.url,
                        'title': self._current_session.title,
                        'start': self._current_session.start_time.isoformat(),
                        'end': self._current_session.end_time.isoformat(),
                        'duration_seconds': 7200,
                        'reason': 'cleanup_orphaned'
                    }
                    self._pending_sessions.append(ended_session)
                    
                    # Reset tracker state
                    self._current_session = None
                    self._tracking_active = False
                    
                    logger.info("CLEANUP: Orphaned session cleaned up")
        except Exception as e:
            logger.error(f"Failed to cleanup orphaned sessions: {e}")
    
    def update_settings(self, capture_full_urls: bool):
        """Update settings dynamically"""
        self.capture_full_urls = capture_full_urls
    
    def _get_firefox_profile_path(self) -> Optional[Path]:
        """Get Firefox default profile path - delegates to global function"""
        return get_firefox_profile_path()

    def _lookup_firefox_history(self, tab_title: str) -> Tuple[Optional[str], Optional[str]]:
        """Look up URL from Firefox history (places.sqlite)"""
        profile_path = self._get_firefox_profile_path()
        if not profile_path:
            return None, None
        
        places_db = profile_path / 'places.sqlite'
        if not places_db.exists():
            return None, None
        
        temp_db = None
        try:
            temp_db = self._safe_copy_db(places_db)
            if not temp_db:
                return None, None
            
            conn = sqlite3.connect(f'file:{temp_db}?mode=ro', uri=True)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT url, title FROM moz_places
                WHERE title LIKE ?
                ORDER BY last_visit_date DESC
                LIMIT 1
            ''', (f'%{tab_title[:50]}%',))
            
            row = cursor.fetchone()
            conn.close()
            
            if row:
                url, title = row
                domain = self._extract_domain_from_url(url)
                return url if self.capture_full_urls else None, domain
            
            return None, None
        except Exception as e:
            logger.debug(f"[FIREFOX] History lookup error: {e}")
            return None, None
        finally:
            if temp_db and os.path.exists(temp_db):
                try:
                    os.remove(temp_db)
                except:
                    pass
    
    # ========================================================================
    #   MAIN PUBLIC METHODS
    # ========================================================================
    
    def sample(self, foreground_app: Optional[str], 
               window_title: Optional[str],
               is_idle: bool = False) -> Optional[Dict]:
        """
        Sample current domain state and detect changes.
        
        Called by collector on each heartbeat cycle.
        
        Args:
            foreground_app: Current foreground app name (e.g., 'chrome.exe')
            window_title: Current window title
            is_idle: Whether user is idle
            
        Returns:
            Ended session dict if domain changed, None otherwise
        """
        # Check if a browser is in foreground
        browser_key = self._detect_browser(foreground_app)
        
        # Handle app switch from browser to non-browser
        if self._last_browser and browser_key is None:
            ended = self._end_current_session(reason="app_switch")
            self._last_browser = None
            return ended
        
        if browser_key is None:
            # Not a browser - end current session
            if self._current_session:
                return self._end_current_session(reason="not_browser")
            return None
        
        if is_idle:
            # User is idle - end domain session
            return self._end_current_session(reason="idle")
        
        # Browser is active - update last browser
        self._last_browser = browser_key
        
        # Get current domain using multiple strategies
        current_domain, current_url, title = self._get_active_domain(browser_key, window_title)
        
        # Log what we got from detection
        if current_domain:
            logger.debug(f"[DOMAIN] Detected domain: {current_domain} from {browser_key}")
        else:
            logger.debug(f"[DOMAIN] No domain from CDP/history, window_title='{window_title}', browser={browser_key}")
        
        # IMPORTANT: If domain is None, use fallback (pseudo-domain from title)
        if current_domain is None and window_title:
            tab_title = self._extract_tab_title(window_title, browser_key)
            if tab_title:
                # First try to extract a real domain from the title
                extracted_domain = self._extract_domain_from_title(tab_title)
                if extracted_domain:
                    current_domain = extracted_domain
                    title = tab_title
                    logger.info(f"[DOMAIN] Extracted domain from title: {current_domain}")
                else:
                    # Use pseudo-domain as last resort
                    current_domain = self._sanitize_title_as_domain(tab_title)
                    title = tab_title
                    logger.info(f"[DOMAIN] Using fallback pseudo-domain: {current_domain}")
        
        if current_domain is None:
            # Still couldn't determine domain - keep existing session
            logger.debug("[DOMAIN] Could not determine domain, keeping existing session")
            return None
        
        # Check for domain change
        if self._current_session is None:
            # Start new session
            self._start_session(current_domain, browser_key, current_url, title,
                               raw_window_title=window_title)
            self._tracking_active = True
            return None
        
        if self._current_session.domain != current_domain:
            # Domain changed - end old session and start new one
            ended_session = self._end_current_session(reason="domain_change")
            self._start_session(current_domain, browser_key, current_url, title,
                               raw_window_title=window_title)
            return ended_session
        
        # Same domain - continue session
        return None
    
    def end_session_for_shutdown(self) -> Optional[Dict]:
        """End current session when helper shuts down"""
        return self._end_current_session(reason="shutdown")
    
    def end_session_for_sleep(self) -> Optional[Dict]:
        """End current session when machine sleeps"""
        return self._end_current_session(reason="sleep")
    
    def end_session_for_lock(self) -> Optional[Dict]:
        """End current session when workstation locks"""
        return self._end_current_session(reason="lock")
    
    def get_pending_sessions(self) -> List[Dict]:
        """Get and clear pending sessions for sending"""
        sessions = self._pending_sessions.copy()
        self._pending_sessions.clear()
        return sessions
    
    def get_current_session_info(self) -> Optional[Dict]:
        """Get info about current active session (for debugging)"""
        if self._current_session:
            now = datetime.now(timezone.utc)
            duration = (now - self._current_session.start_time).total_seconds()
            return {
                'domain': self._current_session.domain,
                'browser': self._current_session.browser,
                'duration_so_far': round(duration, 2),
                'start': self._current_session.start_time.isoformat()
            }
        return None
    
    # ========================================================================
    #   STATE PERSISTENCE
    # ========================================================================
    
    def get_state(self) -> Dict:
        """Get state for persistence"""
        state = {
            'last_visit_times': self._last_visit_times,
            'pending_sessions': self._pending_sessions,
        }
        
        if self._current_session:
            state['current_session'] = self._current_session.to_dict()
        
        return state
    
    def set_state(self, state: Dict):
        """Restore state from persistence"""
        self._last_visit_times = state.get('last_visit_times', {})
        self._pending_sessions = state.get('pending_sessions', [])
        
        if 'current_session' in state:
            try:
                self._current_session = DomainSession.from_dict(state['current_session'])
                self._tracking_active = True
                logger.info(f"[DOMAIN] Restored session: {self._current_session.domain}")
            except Exception as e:
                logger.warning(f"[DOMAIN] Failed to restore session: {e}")
    
    # ========================================================================
    #   INTERNAL METHODS
    # ========================================================================
    
    def _detect_browser(self, app_name: Optional[str]) -> Optional[str]:
        """Detect which browser is active based on process name"""
        if not app_name:
            return None
        
        app_lower = app_name.lower()
        
        for browser_key, config in BROWSER_CONFIGS.items():
            if app_lower in config['process_names']:
                return browser_key
        
        return None
    
    def _get_active_domain(self, browser_key: str, 
                          window_title: Optional[str]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Get the active domain for the browser.
        
        Strategy (in order of reliability):
        1. Extract domain from window title using known_sites mapping
        2. CDP + window title matching - Find CDP tab that matches current window title
        3. Parse tab title from window title + history lookup
        4. Fallback to pseudo-domain from title
        
        Returns:
            Tuple of (domain, url, title) or (None, None, None)
        """
        # Extract the tab title from window title first
        tab_title = None
        if window_title:
            tab_title = self._extract_tab_title(window_title, browser_key)
            logger.debug(f"[DOMAIN] Extracted tab title: '{tab_title}' from '{window_title}'")
        
        if not tab_title:
            logger.debug(f"[DOMAIN] No tab title extracted from window: '{window_title}'")
            return None, None, None
        
        # Strategy 1: Try to extract domain from title using known sites (FASTEST)
        # This handles ChatGPT, Gemini, etc. without needing CDP
        domain = self._extract_domain_from_title(tab_title)
        if domain:
            logger.info(f"[DOMAIN] Matched from title: {domain} (title='{tab_title[:30]}')")
            return domain, None, tab_title
        
        # Strategy 2: Try CDP with title matching
        cdp_result = self._cdp_client.get_tab_by_title(tab_title)
        if cdp_result:
            logger.info(f"[DOMAIN] CDP matched: {cdp_result['domain']} (title='{tab_title[:30]}')")
            return cdp_result['domain'], cdp_result['url'], cdp_result['title']
        
        # Strategy 3: Look up in browser history
        config = BROWSER_CONFIGS.get(browser_key)
        if config:
            url, domain = self._lookup_url_from_title(browser_key, tab_title)
            if domain:
                self._update_cache(tab_title, url, domain)
                logger.info(f"[DOMAIN] History lookup: {domain} (title='{tab_title[:30]}')")
                return domain, url, tab_title
        
        # Strategy 4: No match found - return None and let caller use fallback
        logger.debug(f"[DOMAIN] No domain found for title: '{tab_title}'")
        return None, None, tab_title
    
    def _extract_tab_title(self, window_title: str, browser_key: str) -> Optional[str]:
        """Extract just the tab title from full window title"""
        if not window_title:
            return None
        
        # Browser-specific suffix removal
        config = BROWSER_CONFIGS.get(browser_key, {})
        browser_suffix = config.get('title_suffix', '')
        
        # Try exact suffix match
        if browser_suffix and window_title.endswith(browser_suffix):
            tab_title = window_title[:-len(browser_suffix)].strip()
            return tab_title if tab_title else None
        
        # NEW: Try alternate suffixes (for Firefox, Arc, etc.)
        alt_suffixes = config.get('alt_title_suffixes', [])
        for suffix in alt_suffixes:
            if window_title.endswith(suffix):
                tab_title = window_title[:-len(suffix)].strip()
                return tab_title if tab_title else None
        
        # All known suffix variations
        all_suffixes = [
            ' - Google Chrome', ' - Microsoft Edge', ' - Brave',
            ' — Mozilla Firefox', ' - Mozilla Firefox', ' — Firefox',
            ' - Comet', ' — Arc', ' - Arc',
            ' - Opera', ' - Vivaldi',
            ' – Google Chrome', ' – Brave', ' – Microsoft Edge',
        ]
        
        for suffix in all_suffixes:
            if window_title.endswith(suffix):
                return window_title[:-len(suffix)].strip()
        
        # Browser-specific handling for empty titles
        if browser_key == 'brave' and window_title in ['Brave', 'New Tab']:
            return None
        if browser_key == 'firefox' and window_title in ['Mozilla Firefox', 'Firefox', 'New Tab']:
            return None
        if browser_key == 'arc' and window_title == 'Arc':
            return None
        
        # If no suffix found, use whole title (some browsers omit suffix)
        if browser_key in ['brave', 'arc']:
            return window_title.strip()
        
        return window_title
    
    def _lookup_url_from_title(self, browser_key: str, 
                               tab_title: str) -> Tuple[Optional[str], Optional[str]]:
        """Look up URL from browser history matching the tab title"""
        
        # Bug #9 fix: Check cache first to avoid expensive LIKE queries
        # This prevents 300ms+ delay per heartbeat on large history databases
        if tab_title in self._title_url_cache:
            cached_url, cached_domain = self._title_url_cache[tab_title]
            logger.debug(f"[CACHE] Hit for: {tab_title[:30]}... -> {cached_domain}")
            return cached_url, cached_domain
        
        # Route Firefox to special handler (uses places.sqlite instead of History)
        if browser_key == 'firefox':
            return self._lookup_firefox_history(tab_title)
        
        config = BROWSER_CONFIGS.get(browser_key)
        if not config or not config.get('history_path'):
            return None, None
        
        history_path = config['history_path']
        if not history_path.exists():
            return None, None
        
        temp_db = None
        try:
            # Copy DB to temp location (never lock browser DB)
            temp_db = self._safe_copy_db(history_path)
            if not temp_db:
                return None, None
            
            conn = sqlite3.connect(f'file:{temp_db}?mode=ro', uri=True)
            cursor = conn.cursor()
            
            # IMPROVED: Try multiple search strategies
            search_terms = [tab_title]
            
            # Strategy A: Handle Edge's "and X more pages" pattern
            # "Alert 618591 - Cortex XDR and 7 more pages" -> "Alert 618591"
            if ' and ' in tab_title and 'more page' in tab_title.lower():
                clean_title = tab_title.split(' and ')[0].strip()
                if clean_title:
                    search_terms.insert(0, clean_title)  # Try this first
                    logger.debug(f"[HISTORY] Cleaned title: '{clean_title}'")
            
            # Strategy B: Extract first meaningful segment (before " - " separator)
            if ' - ' in tab_title:
                first_segment = tab_title.split(' - ')[0].strip()
                if first_segment and first_segment not in search_terms:
                    search_terms.append(first_segment)
            
            # Strategy C: Take first 30 chars if title is very long
            if len(tab_title) > 50:
                short_title = tab_title[:30]
                if short_title not in search_terms:
                    search_terms.append(short_title)
            
            # Try each search term
            for search_term in search_terms:
                cursor.execute('''
                    SELECT url, title FROM urls 
                    WHERE title LIKE ? 
                    ORDER BY last_visit_time DESC 
                    LIMIT 1
                ''', (f'%{search_term[:50]}%',))
                
                row = cursor.fetchone()
                if row:
                    url, title = row
                    domain = self._extract_domain_from_url(url)
                    if domain:
                        logger.debug(f"[HISTORY] Found via '{search_term[:30]}': {domain}")
                        conn.close()
                        # Cache the result with original tab_title as key
                        self._update_cache(tab_title, url if self.capture_full_urls else None, domain)
                        return url if self.capture_full_urls else None, domain
            
            conn.close()
            return None, None
            
        except Exception as e:
            logger.debug(f"[DOMAIN] History lookup error: {e}")
            return None, None
        finally:
            if temp_db and os.path.exists(temp_db):
                try:
                    os.remove(temp_db)
                except:
                    pass
    
    def _safe_copy_db(self, db_path: Path) -> Optional[str]:
        """Safely copy a database file to temp location"""
        try:
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
            temp_path = temp_file.name
            temp_file.close()
            
            shutil.copy2(db_path, temp_path)
            return temp_path
        except Exception as e:
            logger.debug(f"[DOMAIN] Failed to copy DB: {e}")
            return None
    
    def _extract_domain_from_url(self, url: str) -> Optional[str]:
        """
        Extract domain from URL using enhanced extraction.
        
        This method is called when UIAutomation/CDP fails to read the address bar.
        Uses extract_domain_from_url_enhanced() for comprehensive edge case handling.
        """
        return extract_domain_from_url_enhanced(url, keep_www=False)
    
    def _extract_domain_from_title(self, title: str) -> Optional[str]:
        """
        Try to extract a domain from the title heuristically with validation.

        Strategy:
        1. Check known_sites mapping first (most reliable)
        2. Use regex with strict validation (prevents false positives)

        Returns:
            Domain string if found and validated, None otherwise
        """
        if not title:
            return None

        # QUICK FIX: Ignore localhost/internal titles (prevents false positives)
        title_lower_check = title.lower()
        localhost_keywords = [
            'sentineledge', 'baki', 'localhost', '127.0.0.1', 
            '192.168.', '10.0.', 'dashboard'
        ]
        for keyword in localhost_keywords:
            if keyword in title_lower_check:
                logger.debug(f"[DOMAIN] Ignoring localhost/internal: {title[:50]}")
                return None

        # Known site mappings - keyword in title -> actual domain (PRIORITY 1)
        # This handles known services reliably without regex guessing
        known_sites = {
            # Google services
            'gmail': 'mail.google.com',
            'inbox': 'mail.google.com',
            'youtube': 'youtube.com',
            'google drive': 'drive.google.com',
            'google docs': 'docs.google.com',
            'google sheets': 'docs.google.com',
            'google slides': 'docs.google.com',
            'gemini': 'gemini.google.com',
            'google ai studio': 'aistudio.google.com',
            'google calendar': 'calendar.google.com',
            'google meet': 'meet.google.com',
            'bard': 'gemini.google.com',

            # AI services
            'chatgpt': 'chatgpt.com',
            'chat - openai': 'chatgpt.com',
            'openai': 'chatgpt.com',
            'claude': 'claude.ai',
            'anthropic': 'claude.ai',
            'perplexity': 'perplexity.ai',
            'copilot': 'copilot.microsoft.com',
            'bing chat': 'copilot.microsoft.com',
            'deepseek': 'chat.deepseek.com',

            # Social media
            'linkedin': 'linkedin.com',
            'twitter': 'twitter.com',
            'facebook': 'facebook.com',
            'instagram': 'instagram.com',
            'reddit': 'reddit.com',
            'whatsapp': 'web.whatsapp.com',
            'slack': 'slack.com',
            'discord': 'discord.com',
            'teams': 'teams.microsoft.com',
            'telegram': 'web.telegram.org',
            'zoom': 'zoom.us',

            # Dev/Work
            'github': 'github.com',
            'gitlab': 'gitlab.com',
            'stackoverflow': 'stackoverflow.com',
            'stack overflow': 'stackoverflow.com',
            'jira': 'atlassian.net',
            'confluence': 'atlassian.net',
            'notion': 'notion.so',
            'trello': 'trello.com',
            'asana': 'asana.com',
            'figma': 'figma.com',
            'canva': 'canva.com',
            'hackerrank': 'hackerrank.com',
            'geeksforgeeks': 'geeksforgeeks.org',

            # Cloud platforms
            'aws console': 'console.aws.amazon.com',
            'ec2': 'console.aws.amazon.com',
            's3 bucket': 'console.aws.amazon.com',
            'lambda': 'console.aws.amazon.com',
            'aws': 'console.aws.amazon.com',
            'azure portal': 'portal.azure.com',
            'azure': 'portal.azure.com',
            'gcp': 'console.cloud.google.com',
            'google cloud': 'console.cloud.google.com',

            # Oracle
            'oracle cloud': 'cloud.oracle.com',
            'oracle': 'oracle.com',
            'mylearn oracle': 'mylearn.oracle.com',

            # Microsoft
            'outlook': 'outlook.office.com',
            'office': 'portal.office.com',
            'onedrive': 'onedrive.live.com',
            'sharepoint': 'sharepoint.com',

            # Entertainment
            'amazon': 'amazon.com',
            'netflix': 'netflix.com',
            'spotify': 'spotify.com',
            'twitch': 'twitch.tv',
            'hulu': 'hulu.com',
            'disney+': 'disneyplus.com',
            'prime video': 'primevideo.com',

            # News/Info
            'wikipedia': 'wikipedia.org',
            'medium': 'medium.com',

            # Productivity/Email
            'protonmail': 'protonmail.com',
            'yahoo mail': 'mail.yahoo.com',
            'grammarly': 'grammarly.com',
            'prezi': 'prezi.com',
            'scribd': 'scribd.com',
            'slideshare': 'slideshare.net',
            'udemy': 'udemy.com',

            # HR/Business
            'greythr': 'greythr.com',
            
            # ✅ IMPROVED: Security platforms (mark as NOT domains - Bug #5)
            'cortex xdr': None,  # Explicitly mark as NOT a domain
            'cortex': None,
            'palo alto': None,
            'palo alto networks': None,
            'xdr': None,
            'splunk': 'splunk.com',  # This IS a real domain
            'sentinel': 'portal.azure.com',  # Microsoft Sentinel
            'crowdstrike': 'falcon.crowdstrike.com',
            'carbon black': None,
            'symantec': None,
            'mcafee': None,
            'kaspersky': None,
            'bitdefender': None,
        }

        title_lower = title.lower()

        # Strategy 1: Check known sites first (most reliable)
        for keyword, domain in known_sites.items():
            if keyword in title_lower:
                return domain  # Returns None for explicitly marked non-domains

        # Strategy 2: Look for actual domain-like patterns with strict validation
        # FIXED: More conservative regex with better validation
        patterns = [
            # Match full domain with at least 2 chars before TLD, word boundaries
            r'\b([a-z0-9][-a-z0-9]{1,61}[a-z0-9]?)\.([a-z]{2,}(?:\.[a-z]{2,})?)\b',
        ]

        for pattern in patterns:
            matches = re.finditer(pattern, title_lower)
            for match in matches:
                full_match = match.group(0)
                domain_part = match.group(1)
                tld_part = match.group(2)

                # Validation checks to prevent false positives
                if not self._is_valid_extracted_domain(full_match, domain_part, 
                                                       tld_part, title):
                    continue

                return full_match

        return None

    def _is_valid_extracted_domain(self, full_domain: str, domain_part: str, 
                                    tld_part: str, original_title: str) -> bool:
        """
        Validate that an extracted domain is actually a domain, not random text.

        This method prevents false positives like extracting "x.com" from
        "Use the interface • Cortex XDR".

        Args:
            full_domain: The complete matched domain (e.g., "example.com")
            domain_part: The part before TLD (e.g., "example")
            tld_part: The TLD part (e.g., "com")
            original_title: The original title for context checking

        Returns:
            True if valid domain, False if likely false positive
        """

        # Validation Rule 1: Minimum length checks
        if len(domain_part) < 2:  # Too short (e.g., "x.com")
            logger.debug(f"[DOMAIN] Rejected short domain part: {full_domain}")
            return False

        if len(full_domain) < 5:  # Too short overall
            logger.debug(f"[DOMAIN] Rejected short domain: {full_domain}")
            return False
        
        # ✅ NEW: Extra check for single-letter domains (Bug #5)
        if len(domain_part) == 1:
            logger.debug(f"[DOMAIN] Rejected single-letter domain: {full_domain}")
            return False
        
        # ✅ NEW: Reject domains that are just common single letters/words (Bug #5)
        common_false_positives = {
            'x', 'i', 'a', 'e', 'o', 'u', 'y',  # Single letters
            'to', 'in', 'on', 'at', 'by', 'or', 'if', 'as',  # Common 2-letter words
            'use', 'for', 'the', 'and', 'but', 'not', 'get', 'set',  # Common 3-letter words
            'page', 'step', 'item', 'text', 'data', 'file', 'form',  # UI terms
        }
        if domain_part.lower() in common_false_positives:
            logger.debug(f"[DOMAIN] Rejected common word as domain: {full_domain}")
            return False

        # Validation Rule 2: TLD must be valid (whitelist approach)
        valid_tlds = {
            # Generic TLDs
            'com', 'org', 'net', 'edu', 'gov', 'mil', 'int',
            'io', 'co', 'ai', 'app', 'dev', 'tech', 'online',
            'site', 'website', 'space', 'store', 'blog', 'so',
            'tv', 'us', 'me', 'info', 'biz', 'mobi',

            # Country code TLDs (common ones)
            'uk', 'ca', 'au', 'de', 'fr', 'jp', 'cn', 'in',
            'br', 'mx', 'es', 'it', 'nl', 'se', 'no', 'dk',

            # Two-part TLDs
            'co.uk', 'co.in', 'co.za', 'com.au', 'com.br',
            'co.jp', 'ac.uk', 'gov.uk', 'com.cn'
        }

        if tld_part not in valid_tlds:
            return False

        # Validation Rule 3: Check if it's part of a larger word
        # Look at context around the match in ORIGINAL title (preserves case)
        idx = original_title.lower().find(full_domain)
        if idx != -1:
            # Check character before domain
            if idx > 0:
                char_before = original_title[idx - 1]
                # If preceded by alphanumeric, it's part of a word (like "Cortex" -> "x")
                if char_before.isalnum():
                    return False

            # Check character after domain
            end_idx = idx + len(full_domain)
            if end_idx < len(original_title):
                char_after = original_title[end_idx]
                # If followed by alphanumeric, it's part of a word
                if char_after.isalnum():
                    return False

        # Validation Rule 4: Reject common false positive patterns
        false_positive_patterns = [
            r'^(page|section|chapter|part|item|step)\.',  # e.g., "page.com"
            r'^(and|or|the|use|for|with|from)\.',  # Common words
            r'^[a-z]\.(com|org|net)',  # Single letter domains (usually false)
        ]

        for fp_pattern in false_positive_patterns:
            if re.match(fp_pattern, full_domain, re.IGNORECASE):
                return False

        # Validation Rule 5: Domain should contain at least one vowel (natural domains do)
        vowels = set('aeiou')
        if not any(c in vowels for c in domain_part):
            # Exception: known acronym domains that are valid
            known_acronyms = {'aws', 'gcp', 'cdn', 'api', 'www', 'ftp', 'ssh', 'vpn'}
            if domain_part not in known_acronyms:
                return False

        # Validation Rule 6: Check if domain has reasonable structure
        # Avoid domains with too many consecutive consonants or weird patterns
        if len(domain_part) >= 4:
            # Count consecutive consonants
            max_consonants = 0
            current_consonants = 0
            for char in domain_part:
                if char.isalpha() and char not in vowels:
                    current_consonants += 1
                    max_consonants = max(max_consonants, current_consonants)
                else:
                    current_consonants = 0

            # More than 4 consecutive consonants is suspicious
            if max_consonants > 4:
                return False

        return True
    
    def _sanitize_title_as_domain(self, title: str) -> str:
        """Convert a title to a pseudo-domain for tracking"""
        if not title:
            return "unknown.local"
        
        # Clean the title
        clean = re.sub(r'[^a-zA-Z0-9\s-]', '', title.lower())
        clean = re.sub(r'\s+', '-', clean.strip())
        clean = clean[:50]  # Limit length
        
        if not clean:
            return "unknown.local"
        
        return f"{clean}.local"
    
    def _update_cache(self, title: str, url: Optional[str], domain: str):
        """Update the title-to-URL cache"""
        if len(self._title_url_cache) >= self._cache_max_size:
            # Remove oldest entries
            keys = list(self._title_url_cache.keys())[:self._cache_max_size // 2]
            for key in keys:
                del self._title_url_cache[key]
        
        self._title_url_cache[title] = (url, domain)
    
    def _start_session(self, domain: str, browser_key: str, 
                      url: Optional[str], title: Optional[str],
                      raw_window_title: Optional[str] = None):
        """Start a new domain session"""
        if not domain or not domain.strip():
            logger.debug("Skipping session - no domain detected")
            return

        browser_name = BROWSER_CONFIGS.get(browser_key, {}).get('name', browser_key)
        self._current_session = DomainSession(
            domain=domain,
            browser=browser_name,
            url=url if self.capture_full_urls else None,
            title=title,
            raw_window_title=raw_window_title  # Pass raw window title
        )
        logger.info(f"[DOMAIN] Session started: {domain} ({browser_name})")
    
    def _end_current_session(self, reason: str = "unknown") -> Optional[Dict]:
        """End the current session and return session data"""
        if not self._current_session:
            return None
        
        session_data = self._current_session.end()
        duration = session_data['duration_seconds']
        
        # Only save sessions longer than 2 seconds
        if duration >= 2.0:
            self._pending_sessions.append(session_data)
            logger.info(
                f"[DOMAIN] Session ended ({reason}): {session_data['domain']} "
                f"after {duration:.1f}s"
            )
        else:
            logger.debug(f"[DOMAIN] Discarding short session: {duration:.1f}s")
        
        self._current_session = None
        self._tracking_active = False
        
        return session_data if duration >= 2.0 else None


# ============================================================================
#   LEGACY: Browser History Tracker (for backward compatibility)
# ============================================================================

class BrowserHistoryTracker:
    """
    LEGACY: Extracts new domain visits from browser history.
    
    This is the old approach - kept for backward compatibility.
    New code should use ActiveDomainTracker for accurate session tracking.
    """
    
    def __init__(self, capture_full_urls: bool = False):
        self.capture_full_urls = capture_full_urls
        self._last_visit_times: Dict[str, int] = {}
        self._last_sample_time: Optional[datetime] = None
        self._sample_interval = 120  # Only sample every 120 seconds
    
    def update_settings(self, capture_full_urls: bool):
        self.capture_full_urls = capture_full_urls
    
    def sample(self) -> List[Dict]:
        """Sample browser history for new domain visits (throttled)"""
        now = datetime.now(timezone.utc)
        
        # Throttle history extraction (heavy operation)
        if self._last_sample_time:
            elapsed = (now - self._last_sample_time).total_seconds()
            if elapsed < self._sample_interval:
                return []
        
        self._last_sample_time = now
        
        all_visits = []
        
        for browser_key, config in BROWSER_CONFIGS.items():
            history_path = config.get('history_path')
            if not history_path or not history_path.exists():
                continue
            
            try:
                visits = self._extract_history(browser_key, history_path)
                all_visits.extend(visits)
            except Exception as e:
                logger.debug(f"[HISTORY] Error reading {browser_key}: {e}")
        
        return all_visits
    
    def _extract_history(self, browser_key: str, history_path: Path) -> List[Dict]:
        """Extract new history entries from browser"""
        temp_db = None
        try:
            # Copy to temp file
            temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db').name
            shutil.copy2(history_path, temp_db)
            
            conn = sqlite3.connect(f'file:{temp_db}?mode=ro', uri=True)
            cursor = conn.cursor()
            
            last_visit = self._last_visit_times.get(browser_key, 0)
            
            cursor.execute('''
                SELECT url, title, last_visit_time 
                FROM urls 
                WHERE last_visit_time > ?
                ORDER BY last_visit_time ASC
                LIMIT 100
            ''', (last_visit,))
            
            visits = []
            max_visit_time = last_visit
            
            for url, title, visit_time in cursor.fetchall():
                domain = self._extract_domain(url)
                if domain:
                    visits.append({
                        'domain': domain,
                        'url': url if self.capture_full_urls else None,
                        'title': title,
                        'browser': BROWSER_CONFIGS[browser_key]['name'],
                        'timestamp': datetime.now(timezone.utc).isoformat()
                    })
                max_visit_time = max(max_visit_time, visit_time)
            
            self._last_visit_times[browser_key] = max_visit_time
            conn.close()
            
            return visits
            
        except Exception as e:
            logger.debug(f"[HISTORY] Extract error: {e}")
            return []
        finally:
            if temp_db and os.path.exists(temp_db):
                try:
                    os.remove(temp_db)
                except:
                    pass
    
    def _extract_domain(self, url: str) -> Optional[str]:
        """
        Extract domain from URL using enhanced extraction.
        
        Uses extract_domain_from_url_enhanced() for comprehensive edge case handling:
        - IP addresses, ports for localhost, special protocols, IDN domains
        """
        return extract_domain_from_url_enhanced(url, keep_www=False)
    
    def get_state(self) -> Dict:
        return {'last_visit_times': self._last_visit_times}
    
    def set_state(self, state: Dict):
        self._last_visit_times = state.get('last_visit_times', {})
