"""
Live Telemetry Module
Sends real-time incremental updates to server instead of batch aggregation
Server can directly update DB without computation
"""
from datetime import datetime, timezone
from typing import Dict, Optional
import logging
import time
import json
import math
import threading

from .config import CoreConfig
from .buffer import BufferDB
import collections

# Try to import ZoneInfo (Python 3.9+), fallback to pytz
_ZONEINFO_AVAILABLE = False
_PYTZ_AVAILABLE = False

try:
    from zoneinfo import ZoneInfo
    _ZONEINFO_AVAILABLE = True
except ImportError:
    pass

# Also try pytz as a fallback option
try:
    import pytz
    _PYTZ_AVAILABLE = True
except ImportError:
    pass

logger = logging.getLogger(__name__)


def get_ist_now() -> datetime:
    """Get current time in IST timezone with robust fallback."""
    from datetime import timedelta
    
    # Method 1: Try ZoneInfo (Python 3.9+)
    if _ZONEINFO_AVAILABLE:
        try:
            return datetime.now(ZoneInfo("Asia/Kolkata"))
        except Exception:
            try:
                # Try alternate timezone name
                return datetime.now(ZoneInfo("Asia/Calcutta"))
            except Exception:
                pass
    
    # Method 2: Try pytz with multiple timezone names
    if _PYTZ_AVAILABLE:
        for tz_name in ['Asia/Kolkata', 'Asia/Calcutta']:
            try:
                ist = pytz.timezone(tz_name)
                return datetime.now(ist)
            except Exception:
                continue
    
    # Method 3: Manual UTC+5:30 offset (ALWAYS works - no library needed)
    try:
        utc_now = datetime.now(timezone.utc)
        ist_offset = timezone(timedelta(hours=5, minutes=30))
        return utc_now.astimezone(ist_offset)
    except Exception as e:
        logger.error(f"[LIVE] Failed to get IST time: {e}, using UTC")
        # Last resort: Use UTC and log error
        return datetime.now(timezone.utc)


def validate_duration(value, default=0, max_value=86400, context="duration") -> float:
    """
    Validate duration is a sane number (0-24 hours).
    Prevents NaN, Infinity, and out-of-range values from corrupting data.
    """
    try:
        val = float(value)
        if not (0 <= val <= max_value):  # Max 24 hours
            logger.error(f"[VALIDATION] {context} out of range: {val}s, using {default}s")
            return default
        if math.isnan(val) or math.isinf(val):
            logger.error(f"[VALIDATION] {context} is NaN/Inf: {val}, using {default}s")
            return default
        return val
    except (ValueError, TypeError):
        logger.error(f"[VALIDATION] {context} non-numeric: {value}, using {default}s")
        return default


class LiveTelemetryTracker:
    """
    Tracks live agent state and sends updates every 10 seconds.
    
    Key Features:
    - Tracks DAILY cumulative totals for screen time (Active/Idle/Locked).
    - Persists state locally to survive restarts.
    - Sends current app duration every 10s.
    - Immediately sends app/domain switches.
    """
    
    def __init__(self, config: CoreConfig, buffer: BufferDB, uploader=None):
        self.config = config
        self.buffer = buffer
        self.uploader = uploader
        
        # Load persisted state
        self.current_state = self._load_state()
        
        # Offline Buffer (for critical events like switches)
        self.offline_buffer = collections.deque(maxlen=500)
        
        # ✅ NEW: Check for agent downtime (Bug #3)
        if 'last_heartbeat_time' in self.current_state:
            try:
                last_time = datetime.fromisoformat(self.current_state['last_heartbeat_time'])
                now = datetime.now(timezone.utc)
                downtime_seconds = (now - last_time).total_seconds()

                if downtime_seconds > 120:  # More than 2 minutes
                    downtime_minutes = downtime_seconds / 60
                    logger.warning(f"[LIVE] ⚠️  AGENT DOWNTIME DETECTED: {downtime_minutes:.1f} minutes")
                    logger.warning(f"[LIVE] Last heartbeat: {last_time.isoformat()}")
                    logger.warning(f"[LIVE] Current time:   {now.isoformat()}")
                    logger.warning(f"[LIVE] This gap will NOT be counted in screen time.")

                    # Store downtime event for reporting
                    self.current_state['last_downtime_minutes'] = round(downtime_minutes, 1)
            except Exception as e:
                logger.debug(f"[LIVE] Could not check downtime: {e}")
        
        # Ensure critical fields exist
        if not self.current_state.get('agent_id'):
            self.current_state['agent_id'] = config.agent_id
        
        # ✅ FIXED: Use IST for date calculation (Bug #2)
        today = get_ist_now().date().isoformat()
        if self.current_state.get('today') != today:
            self.current_state.update({
                'today': today,
                'active_seconds': 0,
                'idle_seconds': 0,
                'locked_seconds': 0
            })
            logger.info(f"[LIVE] Initialized for {today} (IST)")
            
        # Ensure app/domain structures
        if 'current_app' not in self.current_state:
            self.current_state['current_app'] = {
                'app_name': None, 'window_title': None, 'session_start': None, 'duration_seconds': 0
            }
        if 'current_domain' not in self.current_state:
            self.current_state['current_domain'] = {
                'domain': None, 'browser': None, 'url': None, 'session_start': None, 'duration_seconds': 0
            }
        
        # Track last state change time for duration calculation
        self.last_state_change_time = datetime.now(timezone.utc)
            
        # Update interval
        self.update_interval = 10  # Send updates every 10 seconds
        self.last_update_time = time.time()
        
        # Statistics
        self.total_heartbeats_processed = 0
        self.total_updates_sent = 0
        self.total_app_switches = 0
        self.total_domain_switches = 0
        
        # Server availability tracking
        self.server_available = False
        self.offline_mode = True  # Start in offline mode until proven otherwise
        
        logger.info("[LIVE] LiveTelemetryTracker initialized (Daily Totals Mode, IST timezone)")
    
    def _load_state(self) -> Dict:
        """Load state from buffer DB"""
        try:
            state_json = self.buffer.get_state('live_telemetry')
            if state_json:
                state = json.loads(state_json)
                # Parse datetimes if needed? JSON stores strings. 
                # We mostly store strings/ints so it's fine.
                return state
        except Exception as e:
            logger.warning(f"[LIVE] Failed to load state: {e}")
        
        return {
            'agent_id': self.config.agent_id,
            'username': 'unknown',
            'last_idle_state': 'active'
        }

    def _save_state(self):
        """Save state to buffer DB"""
        try:
            state_json = json.dumps(self.current_state)
            self.buffer.set_state('live_telemetry', state_json)
        except Exception as e:
            logger.error(f"[LIVE] Failed to save state: {e}")

    def process_heartbeat(self, heartbeat: Dict):
        """
        Process incoming heartbeat and update live state.
        Accumulates DAILY totals.
        """
        try:
            now = datetime.now(timezone.utc)
            self.total_heartbeats_processed += 1
            
            # ✅ NEW: Track when last heartbeat was processed (for downtime detection)
            self.current_state['last_heartbeat_time'] = now.isoformat()
            
            # Extract heartbeat data
            idle_data = heartbeat.get('idle', {})
            app_data = heartbeat.get('app', {})
            username = heartbeat.get('username', 'unknown')
            
            # Update username if present
            if username != 'unknown':
                self.current_state['username'] = username
            
            # --- DAILY SCREEN TIME TRACKING ---
            # 🔧 CRITICAL FIX: Use system_state from StateDetector (authoritative source)
            # idle.state is ONLY for idle transition events, NOT for time accounting
            system_state = heartbeat.get('system_state', 'active')
            idle_state_fallback = idle_data.get('state', 'active')
            current_idle_state = system_state if system_state else idle_state_fallback
            
            # ✅ FIXED: Validate duration value (Bug #7 - Type mismatch)
            raw_heartbeat_interval = heartbeat.get('pulsetime', 10)
            heartbeat_interval = validate_duration(raw_heartbeat_interval, default=10, max_value=180, context="heartbeat_interval")
            
            # Note: domain_data validation moved to line ~310 where it's actually defined

            # Validate app duration
            app_duration = app_data.get("duration", 0)
            app_data["duration"] = validate_duration(app_duration, context="app_duration")
            
            # ✅ IMPROVED: Calculate actual elapsed time (Bug #4)
            if 'last_state_heartbeat_time' in self.current_state:
                try:
                    last_time = datetime.fromisoformat(self.current_state['last_state_heartbeat_time'])
                    actual_elapsed = (now - last_time).total_seconds()
                    
                    # Sanity check: Cap at 180s to support Helper's adaptive polling (120s during lock)
                    if 10 <= actual_elapsed <= 180:
                        heartbeat_interval = actual_elapsed
                        logger.debug(f"[LIVE] Using actual elapsed time: {actual_elapsed:.1f}s")
                    else:
                        logger.debug(f"[LIVE] Elapsed time out of range ({actual_elapsed:.1f}s), using default 10s")
                        heartbeat_interval = 10
                except Exception as e:
                    logger.debug(f"[LIVE] Could not calculate elapsed time: {e}")
                    heartbeat_interval = 10
            
            # Update timestamp for next calculation
            self.current_state['last_state_heartbeat_time'] = now.isoformat()
            
            # ✅ FIXED: Check for day rollover using IST (Bug #2)
            today = get_ist_now().date().isoformat()
            if today != self.current_state.get('today'):
                logger.info(f"[LIVE] 🌅 MIDNIGHT ROLLOVER (IST): {self.current_state.get('today')} → {today}")
                logger.info(f"[LIVE] Final totals for {self.current_state.get('today')}:")
                logger.info(f"  Active:  {self.current_state.get('active_seconds', 0)}s ({self.current_state.get('active_seconds', 0)/3600:.1f}h)")
                logger.info(f"  Idle:    {self.current_state.get('idle_seconds', 0)}s ({self.current_state.get('idle_seconds', 0)/3600:.1f}h)")
                logger.info(f"  Locked:  {self.current_state.get('locked_seconds', 0)}s ({self.current_state.get('locked_seconds', 0)/3600:.1f}h)")

                # Reset counters
                self.current_state['today'] = today
                self.current_state['active_seconds'] = 0
                self.current_state['idle_seconds'] = 0
                self.current_state['locked_seconds'] = 0
                logger.info(f"[LIVE] ✅ Counters reset for new day: {today}")
            
            # Accumulate counters with validated/actual elapsed time
            if current_idle_state == 'active':
                self.current_state['active_seconds'] += heartbeat_interval
            elif current_idle_state == 'idle':
                self.current_state['idle_seconds'] += heartbeat_interval
            elif current_idle_state == 'locked':
                self.current_state['locked_seconds'] += heartbeat_interval
            
            # Detect state changes (active ↔ idle ↔ locked)
            previous_state = self.current_state.get('last_idle_state', 'active')
            if previous_state != current_idle_state:
                # ✅ DISABLED: Helper's StateDetector is authoritative - don't duplicate
                # self._send_state_change_event(now, previous_state, current_idle_state)
                logger.debug(f"[LIVE] State changed: {previous_state} → {current_idle_state} (Helper handles)")
            
            self.current_state['last_idle_state'] = current_idle_state
            
            # --- APP USAGE TRACKING ---
            current_app = app_data.get('current')
            current_title = app_data.get('current_title')
            friendly_name = app_data.get('friendly_name', current_app)
            category = app_data.get('category', 'other')
            is_browser = app_data.get('is_browser', False)
            
            if current_app:
                prev_app = self.current_state['current_app'].get('app_name')
                if prev_app != current_app:
                    # App switched
                    if prev_app:
                        self._send_app_switch_event(now)
                        self.total_app_switches += 1
                    
                    self.current_state['current_app'] = {
                        'app_name': current_app,
                        'friendly_name': friendly_name,
                        'category': category,
                        'is_browser': is_browser,
                        'window_title': current_title,
                        'session_start': now.isoformat(),
                        'duration_seconds': 0
                    }
                    logger.debug(f"[LIVE] App started: {friendly_name}")
                else:
                    # Same app - accumulate duration
                    self.current_state['current_app']['duration_seconds'] += heartbeat_interval
                    self.current_state['current_app']['window_title'] = current_title
            
            # --- DOMAIN USAGE TRACKING ---
            domain_data = heartbeat.get('domain', {})
            if domain_data:
                # Validate domain duration if present
                if domain_data.get("duration_so_far"):
                    domain_data["duration_so_far"] = validate_duration(
                        domain_data["duration_so_far"], 
                        context="domain_duration"
                    )
                
                current_domain = domain_data.get('domain')
                browser = domain_data.get('browser')
                url = domain_data.get('url')
                domain_duration = domain_data.get('duration_so_far', 0)

                if current_domain:
                    prev_domain = self.current_state['current_domain'].get('domain')
                    if prev_domain != current_domain:
                        # Domain switched
                        if prev_domain:
                            self._send_domain_switch_event(now)
                            self.total_domain_switches += 1

                        self.current_state['current_domain'] = {
                            'domain': current_domain,
                            'browser': browser,
                            'url': url,
                            'session_start': now.isoformat(),
                            'duration_seconds': domain_duration if domain_duration > 0 else 0
                        }
                        logger.debug(f"[LIVE] Domain started: {current_domain}")
                    else:
                        # Same domain - update duration
                        if domain_duration > 0:
                            self.current_state['current_domain']['duration_seconds'] = domain_duration
                        else:
                            self.current_state['current_domain']['duration_seconds'] += heartbeat_interval
            else:
                # No domain data from helper - clear any stale domain state to prevent sending invalid requests
                if self.current_state['current_domain']['domain']:
                    logger.debug("[LIVE] Clearing stale domain state (no domain info from helper)")
                    self.current_state['current_domain'] = {
                        'domain': None, 'browser': None, 'url': None, 'session_start': None, 'duration_seconds': 0
                    }
            
            # Save state
            self._save_state()
            
            # Periodic update
            current_time = time.time()
            if current_time - self.last_update_time >= self.update_interval:
                self._send_periodic_update(now)
                self.last_update_time = current_time
            
        except Exception as e:
            logger.error(f"Error processing heartbeat: {e}", exc_info=True)
    
    def _send_request(self, endpoint: str, data: Dict) -> bool:
        """
        Send request to server with offline buffering support.
        
        Buffering Strategy:
        - Critical events (switches): ALWAYS buffer
        - Periodic updates (screentime): DO NOT buffer (next update has better data)
        """
        try:
            # 1. Try to flush buffer if we think we are online
            if self.server_available and self.offline_buffer:
                self._flush_buffer()

            success = False
            if self.uploader and hasattr(self.uploader, '_make_request'):
                response = self.uploader._make_request(endpoint, data)
                if response:
                    success = True
                    if self.offline_mode:
                        logger.info("[LIVE] Server available - Reconnected")
                        self.server_available = True
                        self.offline_mode = False
                        # Flush buffer immediately on reconnection
                        self._flush_buffer()
                    return True
            
            # If we reach here, request failed
            if not self.offline_mode:
                logger.warning(f"[LIVE] Connection lost. Buffering events...")
                self.offline_mode = True
                self.server_available = False
            
            # 2. Buffer critical events
            # We only buffer events that represent a distinct state change (switches)
            # Periodic updates are cumulative, so we can skip them to avoid spam
            should_buffer = endpoint in ['/telemetry/app-switch', '/telemetry/domain-switch']
            
            if should_buffer:
                logger.debug(f"[LIVE] Buffering event: {endpoint}")
                self.offline_buffer.append({
                    'endpoint': endpoint,
                    'data': data,
                    'timestamp': time.time()
                })
            
            return False
            
        except Exception as e:
            if not self.offline_mode:
                logger.error(f"[LIVE] Request failed: {e}")
                self.offline_mode = True
                self.server_available = False
            
            # Buffer only critical events
            if endpoint in ['/telemetry/app-switch', '/telemetry/domain-switch']:
                 self.offline_buffer.append({
                    'endpoint': endpoint,
                    'data': data,
                    'timestamp': time.time()
                })
            return False

    def _flush_buffer(self):
        """Flush buffered offline events."""
        if not self.offline_buffer:
            return

        logger.info(f"[LIVE] Flushing {len(self.offline_buffer)} buffered events...")
        
        # Process buffer
        # We start from the oldest event
        while self.offline_buffer:
            item = self.offline_buffer[0] # Peek
            
            try:
                if self.uploader and hasattr(self.uploader, '_make_request'):
                    # Add a flag to indicate this is a buffered event (optional)
                    data = item['data']
                    data['_buffered'] = True
                    
                    response = self.uploader._make_request(item['endpoint'], data)
                    
                    if response:
                        # Success - remove from buffer
                        self.offline_buffer.popleft()
                    else:
                        # Failed again - stop flushing and wait for next opportunity
                        logger.debug("[LIVE] Flush interrupted - connection unstable")
                        self.server_available = False
                        self.offline_mode = True
                        break
            except Exception as e:
                logger.error(f"[LIVE] Error flushing buffer: {e}")
                break
                
        logger.info(f"[LIVE] Buffer flush complete. Remaining: {len(self.offline_buffer)}")
    
    def _send_periodic_update(self, timestamp: datetime):
        """Send periodic update with DAILY TOTALS"""
        try:
            self.total_updates_sent += 1
            
            # --- SCREEN TIME UPDATE (Daily Totals) ---
            screentime_update = {
                'agent_id': self.current_state['agent_id'],
                'username': self.current_state['username'],
                'date': self.current_state['today'],
                'timestamp': timestamp.isoformat(),
                # Send TOTALS
                'active_seconds': self.current_state['active_seconds'],
                'idle_seconds': self.current_state['idle_seconds'],
                'locked_seconds': self.current_state['locked_seconds'],
                'current_state': self.current_state['last_idle_state']
            }
            
            sent = self._send_request('/telemetry/screentime', screentime_update)
            
            logger.info(
                f"[LIVE] Screen time (Today): active={self.current_state['active_seconds']}s, "
                f"idle={self.current_state['idle_seconds']}s"
                f"{'' if sent else ' (offline)'}"
            )
            
            # --- CURRENT APP UPDATE ---
            if self.current_state['current_app']['app_name']:
                app_state = self.current_state['current_app']
                
                # Clamp duration to valid range (0-86400 seconds = 0-24 hours)
                # This prevents database constraint violations
                raw_duration = app_state['duration_seconds']
                clamped_duration = max(0, min(raw_duration, 86400))
                if raw_duration != clamped_duration:
                    logger.warning(f"[LIVE] App duration clamped: {raw_duration} -> {clamped_duration}")
                
                app_update = {
                    'agent_id': self.current_state['agent_id'],
                    'username': self.current_state['username'],
                    'timestamp': timestamp.isoformat(),
                    'app': app_state['app_name'],
                    'friendly_name': app_state.get('friendly_name', app_state['app_name']),
                    'category': app_state.get('category', 'other'),
                    'is_browser': app_state.get('is_browser', False),
                    'window_title': app_state['window_title'],
                    'session_start': app_state['session_start'],
                    'duration_seconds': clamped_duration,  # Use clamped value
                    'state': self.current_state['last_idle_state'],  # Include idle state!
                    'is_active': True
                }
                self._send_request('/telemetry/app-active', app_update)
            
            # --- CURRENT DOMAIN UPDATE ---
            if self.current_state['current_domain']['domain']:
                domain_state = self.current_state['current_domain']
                
                # Clamp domain duration to valid range (0-86400 seconds)
                raw_domain_duration = domain_state['duration_seconds']
                clamped_domain_duration = max(0, min(raw_domain_duration, 86400))
                
                domain_update = {
                    'agent_id': self.current_state['agent_id'],
                    'username': self.current_state['username'],
                    'timestamp': timestamp.isoformat(),
                    'domain': domain_state['domain'],
                    'browser': domain_state['browser'],
                    'url': domain_state['url'],
                    'session_start': domain_state['session_start'],
                    'duration_seconds': clamped_domain_duration,
                    'is_active': True
                }
                self._send_request('/telemetry/domain-active', domain_update)
            
        except Exception as e:
            logger.error(f"Error sending periodic update: {e}", exc_info=True)
    
    def _send_app_switch_event(self, timestamp: datetime):
        """Send app switch event"""
        try:
            app = self.current_state['current_app']
            
            # Calculate final duration
            start_ts = datetime.fromisoformat(app['session_start'].replace('Z', '+00:00')) if app['session_start'] else timestamp
            duration = (timestamp - start_ts).total_seconds()
            
            # Clamp duration to valid range (prevents negative or >24h values)
            clamped_duration = max(0, min(duration, 86400))
            if duration != clamped_duration:
                logger.warning(f"[LIVE] App switch duration clamped: {duration:.1f} -> {clamped_duration}")
            
            app_switch = {
                'agent_id': self.current_state['agent_id'],
                'username': self.current_state['username'],
                'timestamp': timestamp.isoformat(),
                'app': app['app_name'],
                'friendly_name': app.get('friendly_name', app['app_name']),
                'category': app.get('category', 'other'),
                'window_title': app['window_title'],
                'session_start': app['session_start'],
                'session_end': timestamp.isoformat(),
                'total_seconds': clamped_duration,
                'is_active': False
            }
            
            self._send_request('/telemetry/app-switch', app_switch)
            
        except Exception as e:
            logger.error(f"Error sending app switch: {e}")
    
    def _send_domain_switch_event(self, timestamp: datetime):
        """Send domain switch event"""
        try:
            domain = self.current_state['current_domain']
            
            start_ts = datetime.fromisoformat(domain['session_start'].replace('Z', '+00:00')) if domain['session_start'] else timestamp
            duration = (timestamp - start_ts).total_seconds()
            
            # Clamp duration to valid range
            clamped_duration = max(0, min(duration, 86400))
            
            domain_switch = {
                'agent_id': self.current_state['agent_id'],
                'username': self.current_state['username'],
                'timestamp': timestamp.isoformat(),
                'domain': domain['domain'],
                'browser': domain['browser'],
                'url': domain['url'],
                'session_start': domain['session_start'],
                'session_end': timestamp.isoformat(),
                'total_seconds': clamped_duration,
                'is_active': False
            }
            
            self._send_request('/telemetry/domain-switch', domain_switch)
            
        except Exception as e:
            logger.error(f"Error sending domain switch: {e}")
    
    def _send_state_change_event(self, timestamp: datetime, previous_state: str, current_state_value: str):
        """Send state change event (active <-> idle <-> locked)"""
        try:
            # ✅ IMPROVED: Calculate duration in previous state (Improvement #2)
            duration = (timestamp - self.last_state_change_time).total_seconds()
            self.last_state_change_time = timestamp
            
            state_change = {
                'agent_id': self.current_state['agent_id'],
                'username': self.current_state['username'],
                'timestamp': timestamp.isoformat(),
                'previous_state': previous_state,
                'current_state': current_state_value,
                'duration_seconds': round(duration, 2)  # ✅ Added duration
            }
            
            self._send_request('/telemetry/state-change', state_change)
            
        except Exception as e:
            logger.error(f"Error sending state change: {e}")

    def get_stats(self) -> Dict:
        """Get current statistics for dashboard"""
        app_name = self.current_state['current_app'].get('app_name', 'unknown')
        app_friendly = self.current_state['current_app'].get('friendly_name', app_name)
        
        return {
            'total_heartbeats': self.total_heartbeats_processed,
            'total_updates': self.total_updates_sent,
            'server_available': self.server_available,
            'offline_mode': self.offline_mode,
            'current_state': self.current_state.get('last_idle_state', 'unknown'),
            'current_app': app_friendly,
            'current_app_exe': app_name,
            'counters': {
                'active_seconds': self.current_state.get('active_seconds', 0),
                'idle_seconds': self.current_state.get('idle_seconds', 0),
                'locked_seconds': self.current_state.get('locked_seconds', 0)
            },
            'today': self.current_state.get('today'),
            'last_updated': datetime.fromtimestamp(self.last_update_time).isoformat()
        }
