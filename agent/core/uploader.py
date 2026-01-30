"""
Uploader Module
Enhanced with certificate pinning and bounded registration retry
Phase-1: Added local development server flags

ARCHITECTURE NOTE:
- This uploader sends RAW data only
- Server handles ALL calculations via stored procedures
- Screen time, app usage, domain usage are calculated server-side
- This prevents duplication and race conditions
"""
import json
import uuid
import time
import platform
import ssl
import hashlib
import os
from datetime import datetime, timezone, date
from typing import Dict, Optional
import logging
import urllib.request
import urllib.error

from .config import CoreConfig
from .buffer import BufferDB

logger = logging.getLogger(__name__)


def get_accurate_os_version() -> str:
    """
    Get accurate Windows version including Windows 11 detection.
    
    Windows 11 reports as Windows 10 in legacy APIs (platform.platform()).
    This function checks the build number to correctly identify Windows 11.
    
    Windows 11: Build >= 22000
    Windows 10: Build 10240-21999
    
    Returns:
        Accurate OS version string like "Windows 11 (Build 22621)" or "Windows-10-10.0.19045"
    """
    import sys
    
    system = platform.system()
    
    if system == "Windows":
        try:
            # Get Windows build number from sys.getwindowsversion()
            if hasattr(sys, 'getwindowsversion'):
                winver = sys.getwindowsversion()
                build = winver.build
                major = winver.major
                minor = winver.minor
                
                # Windows 11 detection: Build >= 22000
                if build >= 22000:
                    return f"Windows 11 (Build {build})"
                elif build >= 10240:
                    return f"Windows 10 (Build {build})"
                elif major == 6 and minor == 3:
                    return f"Windows 8.1 (Build {build})"
                elif major == 6 and minor == 2:
                    return f"Windows 8 (Build {build})"
                elif major == 6 and minor == 1:
                    return f"Windows 7 (Build {build})"
                else:
                    return f"Windows {major}.{minor} (Build {build})"
        except Exception as e:
            logger.debug(f"Error detecting Windows version: {e}")
        
        # Try registry as fallback (more reliable for product name)
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, 
                r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
            )
            try:
                product_name = winreg.QueryValueEx(key, "ProductName")[0]
                current_build = winreg.QueryValueEx(key, "CurrentBuild")[0]
                
                # Fix ProductName if it says Windows 10 but build is 22000+
                if "Windows 10" in product_name and int(current_build) >= 22000:
                    product_name = product_name.replace("Windows 10", "Windows 11")
                
                winreg.CloseKey(key)
                return f"{product_name} (Build {current_build})"
            finally:
                winreg.CloseKey(key)
        except Exception as e:
            logger.debug(f"Registry fallback failed: {e}")
    
    # Fallback for non-Windows or if detection fails
    return platform.platform()


def get_windows_edition() -> Optional[str]:
    """
    Get Windows edition (Pro, Home, Enterprise, etc.)
    Only works on Windows.
    """
    if platform.system() != 'Windows':
        return None
    
    try:
        import winreg
        
        # Read ProductName from registry
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
        )
        
        product_name, _ = winreg.QueryValueEx(key, "ProductName")
        winreg.CloseKey(key)
        
        # Clean up the name
        if "Pro" in product_name:
            return "Pro"
        elif "Home" in product_name:
            return "Home"
        elif "Enterprise" in product_name:
            return "Enterprise"
        elif "Education" in product_name:
            return "Education"
        elif "Server" in product_name:
            return "Server"
        else:
            return "Unknown"
    
    except Exception as e:
        logger.debug(f"Could not detect Windows edition: {e}")
        return None


def get_complete_system_info() -> dict:
    """
    Get complete system information for agent registration.
    Returns dict with os_name, os_version, os_build, edition, architecture.
    """
    import sys
    
    info = {
        'os_name': get_accurate_os_version(),
        'os_version': platform.version(),
        'os_build': None,
        'os_edition': None,
        'platform': platform.system(),
        'architecture': platform.machine(),
        'python_version': f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    }
    
    # Add Windows-specific info
    if platform.system() == 'Windows':
        try:
            if hasattr(sys, 'getwindowsversion'):
                info['os_build'] = sys.getwindowsversion().build
        except:
            pass
        
        edition = get_windows_edition()
        if edition:
            info['os_edition'] = edition
    
    return info


def get_os_build() -> Optional[int]:
    """
    Get Windows build number only (e.g., 22631).
    
    Returns:
        Build number as integer, or None if not Windows/unavailable
    """
    import sys
    
    if platform.system() != "Windows":
        return None
    
    # Try sys.getwindowsversion() first (fastest)
    try:
        if hasattr(sys, 'getwindowsversion'):
            return sys.getwindowsversion().build
    except Exception as e:
        logger.debug(f"Failed to get build from sys: {e}")
    
    # Fallback to registry
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
        )
        try:
            build_str = winreg.QueryValueEx(key, "CurrentBuild")[0]
            return int(build_str)
        finally:
            winreg.CloseKey(key)
    except Exception as e:
        logger.debug(f"Failed to get build from registry: {e}")
    
    return None


def get_architecture() -> str:
    """
    Get system architecture (AMD64, x86, ARM64, etc.).
    
    Returns:
        Architecture string from platform.machine()
    """
    return platform.machine()


class CertificatePinningError(Exception):
    """Certificate pinning validation failed"""
    pass


# ============================================================================
# SEC-021: Certificate Fingerprint Extraction
# ============================================================================
def get_certificate_fingerprint(hostname: str, port: int = 443) -> Optional[str]:
    """
    Get SHA256 fingerprint of server certificate.
    
    SEC-021: Used for certificate pinning verification.
    
    Args:
        hostname: Server hostname
        port: Server port (default 443)
        
    Returns:
        SHA256 fingerprint in uppercase hex, or None if failed
    """
    import socket
    
    try:
        context = ssl.create_default_context()
        with socket.create_connection((hostname, port), timeout=5) as sock:
            with context.wrap_socket(sock, server_hostname=hostname) as ssock:
                cert_der = ssock.getpeercert(binary_form=True)
                fingerprint = hashlib.sha256(cert_der).hexdigest()
                return fingerprint.upper()
    except Exception as e:
        logger.error(f"SEC-021: Failed to get certificate fingerprint: {e}")
        return None

class ServerUploader:
    """Uploads data to server with security enhancements - Config-driven"""
    
    def __init__(self, config: CoreConfig, buffer: BufferDB):
        self.config = config
        self.buffer = buffer
        self.registered = False
        self.auth_failed = False  # Track auth failure to stop uploads
        self.enabled = True  # Can be toggled via config
        self.logger = logging.getLogger('ServerUploader')
        
        # Registration retry tracking
        self.registration_attempts = 0
        self.last_registration_failure = 0
        self.registration_backoff_until = 0
        
        # Rate limiting for spam prevention
        self.last_warning_time = {}
        self.warning_interval = 60  # seconds
        
        # Data signing for tamper resistance
        self.data_signer = None
        try:
            from .integrity import DataSigner
            from pathlib import Path
            key_file = Path(config.data_dir) / '.signing_key'
            self.data_signer = DataSigner(key_file=key_file)
            self.logger.info("[SECURITY] Data signing enabled")
        except Exception as e:
            self.logger.warning(f"[SECURITY] Data signing unavailable: {e}")
        
        # Apply initial config
        self.apply_config(config)
    
    def sign_data(self, data: Dict) -> Dict:
        """Sign data payload if signer is available"""
        if self.data_signer:
            try:
                return self.data_signer.sign(data)
            except Exception as e:
                self.logger.warning(f"[SECURITY] Signing failed: {e}")
        return data
    
    def apply_config(self, config):
        """Apply configuration changes dynamically"""
        core_config = config.config.get("core", {})
        old_enabled = self.enabled
        self.enabled = core_config.get("enable_uploader", True)
        
        if old_enabled != self.enabled:
            status = "enabled" if self.enabled else "disabled"
            self.logger.info(f"[CONFIG] Uploader {status}")

    
    def _load_token_live(self):
        """Load token fresh from secure storage - single source of truth"""
        # Try secure storage first
        if self.config.secure_storage:
            token = self.config.secure_storage.load_token_securely(str(self.config.config_path))
            if token:
                logger.debug(f"[TOKEN] Loaded from secure storage: {token[:10]}...")
                self.config.api_token = token
                return token
            else:
                logger.warning("[TOKEN] No token in secure storage")
        
        # Try config attribute as fallback
        if self.config.api_token and self.config.api_token != '':
            logger.debug(f"[TOKEN] Using token from config attribute: {self.config.api_token[:10]}...")
            return self.config.api_token
        
        # Absolutely no token available
        logger.error("[TOKEN] No token available anywhere - forcing re-registration")
        self.registered = False
        return None
    
    def _log_warning(self, message: str, key: str = "default"):
        """Log warning with rate limiting to prevent spam"""
        current_time = time.time()
        if key not in self.last_warning_time:
            self.last_warning_time[key] = 0
        
        if current_time - self.last_warning_time[key] > self.warning_interval:
            logger.warning(message)
            self.last_warning_time[key] = current_time
    
    def _make_headers(self):
        """Make headers with API key - X-API-Key format"""
        token = self._load_token_live()
        
        if not token:
            logger.error("[AUTH] Cannot create headers - no API key available")
            logger.error("[AUTH] Registration state will be reset")
            self.registered = False
            return None

        # Use Authorization Bearer header as server expects
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Agent-ID": self.config.agent_id,
            "Content-Type": "application/json",
        }
        
        logger.debug(f"[AUTH] Created headers with Bearer token: {token[:20]}...")
        logger.debug(f"[AUTH] Agent ID: {self.config.agent_id}")
        return headers
    
    def ensure_registered(self) -> bool:
        """Ensure agent is registered with server with bounded retry"""
        if self.registered and self.config.is_registered():
            return True
        
        # Check if we're in backoff period
        current_time = time.time()
        if current_time < self.registration_backoff_until:
            remaining = int(self.registration_backoff_until - current_time)
            logger.info(f"Registration in backoff, {remaining}s remaining")
            return False
        
        # Try to register with server
        return self.register()
    
    def register(self) -> bool:
        """Register agent with server using exact API format"""
        current_time = time.time()
        
        # Check backoff
        if self.registration_attempts >= self.config.max_registration_attempts:
            if current_time - self.last_registration_failure < self.config.registration_backoff_minutes * 60:
                self.registration_backoff_until = current_time + (self.config.registration_backoff_minutes * 60)
                logger.warning(f"Registration failed {self.registration_attempts} times, backing off for {self.config.registration_backoff_minutes} minutes")
                return False
            else:
                self.registration_attempts = 0
        
        try:
            logger.info("=" * 70)
            logger.info("[REGISTER] Starting registration flow...")
            logger.info(f"[REGISTER] Agent ID: {self.config.agent_id}")
            logger.info(f"[REGISTER] Agent Name: {self.config.agent_name}")
            logger.info(f"[REGISTER] Hostname: {platform.node()}")
            # Debug: Show if registration secret is configured
            if self.config.registration_secret:
                masked_secret = self.config.registration_secret[:8] + "***" if len(self.config.registration_secret) > 8 else "***"
                logger.info(f"[REGISTER] Registration secret: {masked_secret} (configured)")
            else:
                logger.warning("[REGISTER] ⚠️ Registration secret: NOT CONFIGURED!")
                logger.warning("[REGISTER] Check config.json -> server -> registration_secret")
            logger.info("=" * 70)
            
            # Match exact specification format (include local_agent_key for server validation)
            payload = {
                'agent_id': self.config.agent_id,
                'agent_name': self.config.agent_name,  # Custom display name
                'local_agent_key': self.config.local_agent_key,
                'hostname': platform.node(),
                'os_version': get_accurate_os_version(),
                'os_build': get_os_build(),  # NEW: Build number (e.g., 22631)
                'windows_edition': get_windows_edition(),  # NEW: Pro/Home/Enterprise
                'architecture': get_architecture(),  # NEW: AMD64/x86/ARM64
                'agent_version': '2.0.0'
            }
            
            logger.info(f"[REGISTER] Sending registration request to {self.config.server_url}/api/v1/register")
            logger.debug(f"[REGISTER] Payload: {payload}")
            
            response = self._make_request('/register', payload, use_auth=False)
            
            if not response:
                self._log_warning("[REGISTER] No response from server (offline?)", "register_offline")
                self.registration_attempts += 1
                self.last_registration_failure = time.time()
                return False
            
            logger.debug(f"[REGISTER] Server response: {response}")
            
            # Extract API key from response (try api_key first, then api_token for backward compatibility)
            api_key = response.get('api_key') or response.get('api_token')
            
            if not api_key:
                logger.error(f"[REGISTER] ERROR: No 'api_key' in response")
                logger.error(f"[REGISTER] Response keys: {list(response.keys())}")
                logger.error(f"[REGISTER] Full response: {response}")
                self.registration_attempts += 1
                self.last_registration_failure = time.time()
                return False
            
            logger.info("=" * 70)
            logger.info(f"[REGISTER] SUCCESS: Received API key: {api_key[:20]}...")
            logger.info("=" * 70)
            
            # Verify agent data in response
            agent_data = response.get('agent', {})
            server_agent_id = agent_data.get('agent_id') or response.get('agent_id')
            
            if server_agent_id and server_agent_id != self.config.agent_id:
                logger.warning(f"[REGISTER] Server assigned different Agent ID: {self.config.agent_id} -> {server_agent_id}")
                
                # Use set_agent_id to atomically update memory and disk
                try:
                    self.config.set_agent_id(server_agent_id)
                except Exception as e:
                    logger.error(f"[REGISTER] Failed to adopt server-assigned ID: {e}")
            
            logger.info(f"[REGISTER] Agent status: {agent_data.get('status', 'unknown')}")
            logger.info(f"[REGISTER] Last seen: {agent_data.get('last_seen', 'unknown')}")
            
            # CRITICAL: Store API key securely
            logger.info("[REGISTER] Storing API key securely...")
            
            if self.config.secure_storage:
                success = self.config.secure_storage.store_token_securely(
                    api_key, 
                    str(self.config.config_path)
                )
                
                if not success:
                    logger.error("[REGISTER] FAILED to persist API key - will retry next cycle")
                    self.registration_attempts += 1
                    self.last_registration_failure = time.time()
                    return False
                
                logger.info("[REGISTER] API key stored in secure storage")
            else:
                logger.warning("[REGISTER] No secure storage available, using plaintext")
                self.config.config['api_key'] = api_key
                self.config.config['api_token'] = api_key  # Backward compatibility
            
            # Verify storage worked (only if secure storage is available)
            logger.info("[REGISTER] Verifying API key persistence...")
            
            if self.config.secure_storage:
                loaded_key = self.config.secure_storage.load_token_securely(str(self.config.config_path))
                
                if not loaded_key or loaded_key != api_key:
                    logger.error("[REGISTER] API key verification FAILED after storage")
                    logger.error(f"[REGISTER] Stored: {api_key[:10]}..., Loaded: {loaded_key[:10] if loaded_key else 'None'}...")
                    self.registration_attempts += 1
                    self.last_registration_failure = time.time()
                    return False
                
                logger.info("[REGISTER] API key verification successful (secure storage)")
            else:
                # No secure storage - verify from config
                loaded_key = self.config.config.get('api_key') or self.config.config.get('api_token')
                if not loaded_key:
                    logger.error("[REGISTER] API key not found in config after storage")
                    return False
                logger.info("[REGISTER] API key stored in plaintext config (no secure storage)")
            
            # Update config object - set BOTH api_token and api_key
            self.config.api_token = loaded_key
            self.config.api_key = loaded_key
            self.config.save_config()
            
            # Mark as registered
            self.registered = True
            self.registration_attempts = 0
            
            logger.info("=" * 70)
            logger.info("[REGISTER] Registration complete and verified")
            logger.info(f"[REGISTER] Agent {self.config.agent_id} is now registered")
            logger.info("=" * 70)
            
            return True
            
        except Exception as e:
            logger.error(f"[REGISTER] Registration error: {e}", exc_info=True)
            self.registration_attempts += 1
            self.last_registration_failure = time.time()
            return False
    
    def handle_auth_failure(self):
        """Handle authentication failure - do NOT clear stored tokens"""
        logger.warning("Authentication failed - stopping uploads")
        self.registered = False
        # Do NOT clear stored tokens on 401/403
    
    def _validate_certificate(self, https_conn):
        """
        Validate server certificate against pinned fingerprint.
        
        SEC-021: Certificate pinning prevents MITM attacks by verifying
        the server's certificate matches a known fingerprint.
        """
        # Skip if disabled via config (development/testing mode)
        if self.config.skip_cert_pinning:
            logger.debug("SEC-021: Certificate pinning disabled by config flag")
            return True
        
        # Get expected fingerprint from config
        expected_fingerprint = self.config.get_server_cert_fingerprint()
        
        if not expected_fingerprint:
            logger.debug("SEC-021: No certificate fingerprint configured, skipping validation")
            return True
        
        try:
            # Get the certificate in binary DER format
            cert_der = https_conn.getpeercert(binary_form=True)
            
            if not cert_der:
                logger.warning("SEC-021: No certificate received from server")
                return False
            
            # Calculate SHA256 fingerprint of the DER-encoded certificate
            fingerprint = hashlib.sha256(cert_der).hexdigest().upper()
            
            # Compare fingerprints (case-insensitive)
            if fingerprint != expected_fingerprint.upper():
                logger.critical("=" * 70)
                logger.critical("SEC-021: CERTIFICATE PINNING FAILED!")
                logger.critical(f"Expected: {expected_fingerprint.upper()}")
                logger.critical(f"Actual:   {fingerprint}")
                logger.critical("Possible MITM attack detected!")
                logger.critical("=" * 70)
                
                raise CertificatePinningError(
                    f"Certificate fingerprint mismatch. Expected: {expected_fingerprint}, Got: {fingerprint}"
                )
            
            logger.debug("SEC-021: Certificate fingerprint validated successfully")
            return True
            
        except CertificatePinningError:
            raise
        except Exception as e:
            logger.warning(f"SEC-021: Certificate validation error: {e}")
            return False
    
    def _make_request(
        self,
        endpoint: str,
        data: Dict,
        use_auth: bool = True,
        timeout: int = 30
    ) -> Optional[Dict]:
        """Make HTTP request to server with certificate pinning and Phase-1 flags"""
        max_retries = 2
        retry_count = 0
        
        while retry_count <= max_retries:
            try:
                # Add /api/v1 prefix to match server's URL structure
                api_endpoint = f"/api/v1{endpoint}" if not endpoint.startswith("/api/") else endpoint
                url = f"{self.config.server_url}{api_endpoint}"
                json_data = json.dumps(data).encode('utf-8')
                
                # Determine headers based on whether auth is required
                if use_auth:
                    headers = self._make_headers()
                    if not headers:
                        logger.error("Cannot make request - no auth headers available")
                        return None
                else:
                    # Register and other unauthenticated endpoints must not include Authorization
                    headers = {
                        "Content-Type": "application/json"
                    }
                    # SEC-002: Add registration secret for /register endpoint
                    if self.config.registration_secret:
                        headers["X-Registration-Secret"] = self.config.registration_secret
                
                req = urllib.request.Request(
                    url,
                    data=json_data,
                    headers=headers,
                    method='POST'
                )
                
                # Phase-1: Skip HTTPS context creation for HTTP URLs
                context = None
                if url.startswith('https://') and not self.config.allow_insecure_http:
                    context = ssl.create_default_context()
                    
                    # Custom certificate verification
                    def verify_cert(conn, url, cert, errnum, errdepth, retcode):
                        if retcode == 0:  # Pre-verification
                            return self._validate_certificate(conn)
                        return retcode
                    
                    context.verify_mode = ssl.CERT_REQUIRED
                    # Note: Full certificate pinning requires more complex implementation
                    # This is a simplified version for demonstration
                
                with urllib.request.urlopen(req, timeout=timeout, context=context) as response:
                    response_data = response.read().decode('utf-8')
                    if response_data:
                        return json.loads(response_data)
                    return {'status': 'ok'}
                    
            except urllib.error.HTTPError as e:
                logger.error(f"[REQUEST] HTTP {e.code} for {endpoint}: {e.reason}")
                
                # Handle 401 Unauthorized with automatic re-registration
                if e.code == 401 and use_auth:
                    logger.warning("=" * 70)
                    logger.warning("[AUTH] 401 Unauthorized - API key invalid or expired")
                    logger.warning("[AUTH] Attempting automatic re-registration...")
                    logger.warning("=" * 70)
                    
                    self.registered = False  # Mark as unregistered
                    
                    # Attempt re-registration (with bounded retry)
                    if retry_count < max_retries:
                        logger.info(f"[AUTH] Re-registration attempt {retry_count + 1}/{max_retries}")
                        
                        if self.register():
                            logger.info("[AUTH] Re-registration successful")
                            logger.info("[AUTH] Retrying original request...")
                            retry_count += 1
                            time.sleep(1)  # Brief pause before retry
                            continue
                        else:
                            logger.error("[AUTH] Re-registration failed")
                            return None
                    else:
                        logger.error(f"[AUTH] Max retries ({max_retries}) exceeded")
                        return None
                
                # Handle other HTTP errors (403, 400, 500, etc.)
                if e.code == 403 and use_auth:
                    self._log_warning(f"[AUTH] 403 Forbidden - access denied", "auth_forbidden")
                    self.registered = False
                
                try:
                    error_body = e.read().decode('utf-8')
                    logger.error(f"[REQUEST] Error body: {error_body}")
                except:
                    pass
                return None
                
            except CertificatePinningError as e:
                logger.error(f"Certificate pinning failed: {e}")
                return None
                
            except Exception as e:
                # Use debug level for network errors to avoid log spam when offline
                logger.debug(f"Request error for {endpoint}: {e}")
                if retry_count < max_retries:
                    retry_count += 1
                    time.sleep(1)
                    continue
                return None
        
        return None
    
    def upload_batch(self):
        """Upload a batch of data to server"""
        # Check if uploader is enabled
        if not self.enabled:
            return
        
        if not self.ensure_registered():
            self._log_warning("Not registered, skipping upload", "not_registered")
            return
        
        try:
            # Upload merged events (heartbeat data)
            self._upload_merged_events()
            
            # Upload domains (legacy history-based)
            self._upload_domains()
            
            # Upload domain sessions (NEW - session-based)
            self._upload_domain_sessions()
            
            # Upload state spans (NEW - Idempotent screen time tracking)
            self._upload_state_spans()
            
            # Upload inventory
            self._upload_inventory()
            
            # Send current status (from latest heartbeat)
            self._send_current_status()
            
            # Send heartbeat
            self._send_heartbeat()
            
        except Exception as e:
            logger.error(f"Upload batch error: {e}", exc_info=True)

    def _send_current_status(self):
        """Send current app/idle status from latest heartbeat"""
        try:
            heartbeat = self.buffer.get_latest_heartbeat()
            if not heartbeat:
                return

            app_data = heartbeat.get('app', {})
            idle_data = heartbeat.get('idle', {})
            
            # Clamp duration to valid range (0-86400 seconds)
            raw_duration = app_data.get('duration', 0)
            clamped_duration = max(0, min(raw_duration, 86400))
            
            payload = {
                'agent_id': self.config.agent_id,
                'username': heartbeat.get('username', 'unknown'),
                'timestamp': heartbeat.get('timestamp'),
                'app': app_data.get('current'),
                'friendly_name': app_data.get('friendly_name'),
                'window_title': app_data.get('current_title'),
                'duration_seconds': clamped_duration,
                
                # Use system_state from state detector (new agents)
                # Falls back to old state field for backward compatibility
                'system_state': heartbeat.get('system_state') or idle_data.get('state', 'active')
            }
            
            # Send to live telemetry endpoint
            self._make_request('/telemetry/app-active', payload)
            
        except Exception as e:
            logger.error(f"Error sending current status: {e}")
    
    def _upload_merged_events(self):
        """Upload merged events - route to correct endpoint by type"""
        events = self.buffer.get_unuploaded_merged_events(limit=500)
        if not events:
            return
        
        uploaded_ids = []
        
        for event in events:
            event_type = event.get('type', '')
            
            # STATE-CHANGE: Instant events from lock/unlock - NOT from aggregator
            # These are stored directly by ingest.py._handle_state_change()
            if event_type == 'state-change':
                state = event.get('state', {})
                previous_state = state.get('previous_state')
                current_state = state.get('current_state')
                
                # Skip if data is corrupted/missing
                if not previous_state or not current_state:
                    logger.warning(f"Skipping corrupted state-change event: {event}")
                    uploaded_ids.append(event['id'])  # Mark as processed to skip it
                    continue
                
                payload = {
                    'agent_id': event.get('agent_id'),
                    'username': event.get('username', 'unknown'),
                    'previous_state': previous_state,
                    'current_state': current_state,
                    'timestamp': event.get('start'),
                    'duration_seconds': event.get('duration_seconds', 0)
                }
                response = self._make_request('/telemetry/state-change', payload)
            
            # SCREEN EVENTS: From aggregator's _merge_idle_states()
            elif event_type in ['screen-active', 'screen-idle', 'screen-locked']:
                # Extract previous state from event (aggregator stores it in 'state' field)
                # The 'state' represents what the user WAS doing during this duration
                previous_state = event.get('state', {}).get('state', 'unknown')
                
                # Send to state-change endpoint
                payload = {
                    'agent_id': event.get('agent_id'),
                    'username': event.get('username', 'unknown'),
                    'previous_state': previous_state,  # State user WAS in (for duration attribution)
                    'current_state': previous_state,   # Same value for StateChange record
                    'timestamp': event.get('start'),
                    'duration_seconds': event.get('duration_seconds', 0)
                }
                response = self._make_request('/telemetry/state-change', payload)
                
            elif event_type == 'app':
                # Send to app-switch endpoint
                state = event.get('state', {})
                app_name = state.get('app_name', 'unknown')
                
                # Skip if app is None/null (idle period)
                if not app_name or app_name in ['None', 'null', 'unknown']:
                    logger.debug(f"Skipping app event with null app_name (idle period)")
                    uploaded_ids.append(event['id'])  # Mark as uploaded to avoid retry
                    continue
                
                # Clamp duration to valid range (0-86400 seconds)
                raw_duration = event.get('duration_seconds', 0)
                clamped_duration = max(0, min(raw_duration, 86400))
                if raw_duration != clamped_duration:
                    logger.warning(f"[UPLOAD] App duration clamped: {raw_duration} -> {clamped_duration}")
                
                payload = {
                    'agent_id': event.get('agent_id'),
                    'username': event.get('username', 'unknown'),
                    'app': app_name,
                    'friendly_name': app_name,
                    'category': 'other',
                    'window_title': state.get('window_title', ''),
                    'session_start': event.get('start'),
                    'session_end': event.get('end'),
                    'total_seconds': clamped_duration,
                    'timestamp': event.get('end')
                }
                response = self._make_request('/telemetry/app-switch', payload)
            
            elif event_type == 'screentime':
                # Get cumulative values from state dict (aggregator sums deltas)
                # Server expects: active_seconds, idle_seconds, locked_seconds (NOT delta_*)
                state = event.get('state', {})
                payload = {
                    'agent_id': event.get('agent_id'),
                    'username': event.get('username', 'unknown'),
                    'timestamp': event.get('start'),  # Buffer stores as 'start'
                    'active_seconds': state.get('delta_active_seconds', 0),  # Cumulative total
                    'idle_seconds': state.get('delta_idle_seconds', 0),      # Cumulative total
                    'locked_seconds': state.get('delta_locked_seconds', 0),  # Cumulative total
                    'current_state': state.get('current_state', 'active')
                }
                
                response = self._make_request('/telemetry/screentime', payload)
            else:
                # Unknown type, skip
                continue
            
            if response:
                uploaded_ids.append(event['id'])
        
        # Mark as uploaded
        if uploaded_ids:
            self.buffer.mark_events_uploaded(uploaded_ids)
            logger.info(f"[OK] Uploaded {len(uploaded_ids)} merged events")
    
    def _upload_domains(self):
        """Upload domain visits - server handles calculations"""
        domains = self.buffer.get_unuploaded_domains(limit=500)
        
        if not domains:
            return
        
        # Format for server
        formatted_domains = []
        for domain_record in domains:
            formatted_domains.append({
                'domain': domain_record['domain'],
                'timestamp': domain_record['timestamp'],
                'url': domain_record.get('url'),
                'tab_title': domain_record.get('title'),
                'browser': domain_record.get('browser'),
                'agent_id': domain_record.get('agent_id')
            })
        
        payload = {'domains': formatted_domains}
        response = self._make_request('/domains', payload)
        
        if response:
            # Mark as uploaded
            domain_ids = [d['id'] for d in domains]
            self.buffer.mark_domains_uploaded(domain_ids)
            logger.info(f"[OK] Uploaded {len(domains)} domain visits")
        else:
            logger.debug("Failed to upload domains (server offline?)")
    
    def _upload_domain_sessions(self):
        """Upload domain sessions - uses domain-switch for historical tracking"""
        sessions = self.buffer.get_unuploaded_domain_sessions(limit=500)
        
        if not sessions:
            return
        
        uploaded_ids = []
        
        # Send each session individually to domain-switch endpoint
        # (which stores in domain_sessions and aggregates to domain_usage)
        for session in sessions:
            payload = {
                'agent_id': self.config.agent_id,
                'domain': session.get('domain'),
                'browser': session.get('browser', ''),
                'url': session.get('url'),
                'session_start': session.get('start'),
                'session_end': session.get('end'),
                'total_seconds': session.get('duration_seconds', 0),
                'timestamp': session.get('end')  # Use end time as timestamp
            }
            
            response = self._make_request('/telemetry/domain-switch', payload)
            
            if response and response.get('status') in ('ok', 'success', 'skipped'):
                uploaded_ids.append(session['id'])
        
        # Mark uploaded sessions
        if uploaded_ids:
            self.buffer.mark_domain_sessions_uploaded(uploaded_ids)
            
            total_duration = sum(
                s.get('duration_seconds', 0) for s in sessions 
                if s['id'] in uploaded_ids
            )
            logger.info(f"[OK] Uploaded {len(uploaded_ids)} domain sessions ({total_duration:.0f}s)")
        else:
            logger.debug("Failed to upload domain sessions (server offline?)")
    
    def _upload_inventory(self):
        """Upload inventory snapshots"""
        inventory_records = self.buffer.get_unuploaded_inventory(limit=10)
        
        if not inventory_records:
            return
        
        for record in inventory_records:
            payload = {
                'agent_id': record['agent_id'],
                'timestamp': record['timestamp'],
                'apps': record.get('apps', []),
                'changes': record.get('changes', {})
            }
            
            response = self._make_request('/inventory', payload)
            
            if response:
                self.buffer.mark_inventory_uploaded([record['id']])
                logger.info(f"[OK] Uploaded inventory snapshot: {len(record.get('apps', []))} apps")
            else:
                logger.debug("Failed to upload inventory (server offline?)")
                break  # Stop on first failure
    
    def _send_heartbeat(self):
        """Send heartbeat to server"""
        try:
            if not hasattr(self, 'sequence'):
                self.sequence = 0
            self.sequence += 1
            
            payload = {
                'agent_id': self.config.agent_id,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'sequence': self.sequence
            }
            
            self._make_request('/heartbeat', payload)
        except Exception:
            pass  # Heartbeat failures are not critical
    
    def upload_state_change(self, event_data: Dict) -> bool:
        """
        Upload state-change event immediately to server.
        Called from queue processor for real-time state updates.
        """
        try:
            payload = {
                'agent_id': event_data.get('agent_id', self.config.agent_id),
                'event_type': 'state-change',
                'previous_state': event_data.get('previous_state'),
                'current_state': event_data.get('current_state'),
                'timestamp': event_data.get('timestamp'),
                'username': event_data.get('username', ''),
                'duration_seconds': event_data.get('duration_seconds', 0)
            }
            
            response = self._make_request('/telemetry/state-change', payload)
            
            if response:
                logger.info(
                    f"[STATE] Uploaded state-change: "
                    f"{event_data.get('previous_state')} -> {event_data.get('current_state')}"
                )
                return True
            else:
                logger.debug("State-change upload failed (server offline?)")
                return False
                
        except Exception as e:
            logger.error(f"Failed to upload state-change: {e}")
            return False

    def _upload_state_spans(self):
        """Upload buffered state spans for idempotent screen time tracking"""
        spans = self.buffer.get_unuploaded_state_spans(limit=100)
        
        if not spans:
            return
        
        uploaded_ids = []
        
        # Format payload and send
        payload = {
            'agent_id': self.config.agent_id,
            'spans': [
                {
                    'span_id': s['span_id'],
                    'state': s['state'],
                    'start_time': s['start_time'],
                    'end_time': s['end_time'],
                    'duration_seconds': s['duration_seconds'],
                    'created_at': s['created_at']
                } for s in spans
            ]
        }
        
        response = self._make_request('/telemetry/screentime-spans', payload)
        
        if response:
            uploaded_ids = [s['id'] for s in spans]
            self.buffer.mark_state_spans_uploaded(uploaded_ids)
            logger.info(f"[OK] Uploaded {len(uploaded_ids)} state spans")
        else:
            logger.debug("Failed to upload state spans (server offline?)")

