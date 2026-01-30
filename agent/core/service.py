"""
SentinelEdge Core Service - Enhanced with manifest verification
Phase-1: Added local development server flags
SYSTEM-level service that aggregates and uploads telemetry
Handles system restarts, sleep/wake cycles, and network interruptions
"""
import sys
import time
import logging
import ctypes
import subprocess
import json
from pathlib import Path
from threading import Thread, Event
from datetime import datetime, timezone
from typing import Optional, Callable

# Add core package to path
sys.path.insert(0, str(Path(__file__).parent))

from core.config import CoreConfig
from core.buffer import BufferDB
from core.ingest import IngestServer
from core.aggregator import HeartbeatAggregator
from core.uploader import ServerUploader
from core.live_telemetry import LiveTelemetryTracker

# psutil for process monitoring
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False
    logging.warning("psutil not available, Helper monitoring limited")

# Windows power management
try:
    import win32api
    import win32con
    import win32gui
    import win32service
    import win32serviceutil
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False
    logging.warning("pywin32 not available, power management limited")


class HelperMonitor:
    """
    Monitors Helper process health and auto-restarts if needed.
    Reports DEGRADED mode to server if Helper repeatedly fails.
    """
    
    # Operational statuses
    STATUS_NORMAL = "NORMAL"
    STATUS_DEGRADED = "DEGRADED"
    STATUS_OFFLINE = "OFFLINE"
    
    def __init__(self, config: CoreConfig, uploader, install_dir: Path):
        self.config = config
        self.uploader = uploader
        self.install_dir = install_dir
        self.logger = logging.getLogger('HelperMonitor')
        
        # State tracking
        self.last_heartbeat_time: Optional[datetime] = None
        self.helper_pid: Optional[int] = None
        self.operational_status = self.STATUS_NORMAL
        self.status_reason = ""
        
        # Restart tracking
        self.restart_attempts = 0
        self.max_restart_attempts = 5
        self.last_restart_time: Optional[datetime] = None
        self.restart_cooldown_minutes = 30  # After max attempts, wait 30 min
        
        # Monitoring settings
        self.heartbeat_timeout_seconds = 120  # 2 minutes without heartbeat = problem
        self.check_interval_seconds = 60  # Check every 60 seconds
        
        # Control
        self.running = False
        self.monitor_thread: Optional[Thread] = None
        self.shutdown_event = Event()
        
        self.logger.info("[HelperMonitor] Initialized")
    
    def on_heartbeat_received(self):
        """Called by IngestServer when Helper sends heartbeat"""
        self.last_heartbeat_time = datetime.now(timezone.utc)
        self.logger.debug("[HelperMonitor] Helper heartbeat received")
        
        # If we were in degraded mode and Helper is now working, recover
        if self.operational_status == self.STATUS_DEGRADED:
            self._recover_from_degraded()
    
    def _recover_from_degraded(self):
        """Return to normal operation after Helper recovery"""
        self.logger.info("[HelperMonitor] Helper recovered - returning to NORMAL")
        self.operational_status = self.STATUS_NORMAL
        self.status_reason = ""
        self.restart_attempts = 0
        
        # Notify server
        self._notify_server_status(self.STATUS_NORMAL, "Helper recovered automatically")
    
    def start(self):
        """Start monitoring Helper process"""
        if not HAS_PSUTIL:
            self.logger.warning("[HelperMonitor] Cannot start - psutil not available")
            return
        
        self.running = True
        self.monitor_thread = Thread(
            target=self._monitor_loop,
            daemon=True,
            name="HelperMonitor"
        )
        self.monitor_thread.start()
        self.logger.info("[HelperMonitor] Started")
    
    def stop(self):
        """Stop monitoring"""
        self.running = False
        self.shutdown_event.set()
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)
        self.logger.info("[HelperMonitor] Stopped")
    
    def _monitor_loop(self):
        """Main monitoring loop"""
        # Initial delay to let Helper start
        self.shutdown_event.wait(30)
        
        while self.running and not self.shutdown_event.is_set():
            try:
                self._check_helper_health()
            except Exception as e:
                self.logger.error(f"[HelperMonitor] Error: {e}", exc_info=True)
            
            self.shutdown_event.wait(self.check_interval_seconds)
        
        self.logger.info("[HelperMonitor] Monitor loop stopped")
    
    def _check_helper_health(self):
        """Check if Helper is running and healthy"""
        # 1. Check if Helper process is running
        helper_running = self._find_helper_process()
        
        # 2. Check if we've received heartbeats recently
        heartbeat_ok = self._check_heartbeat_timeout()
        
        if helper_running and heartbeat_ok:
            # All good
            if self.operational_status != self.STATUS_NORMAL:
                self._recover_from_degraded()
            return
        
        # Problem detected
        if not helper_running:
            self.logger.warning("[HelperMonitor] Helper process NOT running")
            self._attempt_restart("Helper process not found")
        elif not heartbeat_ok:
            self.logger.warning("[HelperMonitor] Helper not sending heartbeats")
            self._attempt_restart("Helper not sending heartbeats")
    
    def _find_helper_process(self) -> bool:
        """Find Helper process by looking for pythonw running sentinel_helper"""
        if not HAS_PSUTIL:
            return True  # Assume running if we can't check
        
        try:
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    name = proc.info['name'] or ''
                    cmdline = proc.info['cmdline'] or []
                    
                    # Check for pythonw/python running sentinel_helper
                    if 'python' in name.lower():
                        cmdline_str = ' '.join(cmdline).lower()
                        if 'sentinel_helper' in cmdline_str or 'helper' in cmdline_str:
                            self.helper_pid = proc.info['pid']
                            self.logger.debug(f"[HelperMonitor] Found Helper: PID {self.helper_pid}")
                            return True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            
            self.helper_pid = None
            return False
            
        except Exception as e:
            self.logger.error(f"[HelperMonitor] Process search error: {e}")
            return True  # Assume running on error
    
    def _check_heartbeat_timeout(self) -> bool:
        """Check if we've received heartbeat within timeout window"""
        if self.last_heartbeat_time is None:
            # No heartbeat ever received - allow startup grace period
            return True
        
        elapsed = (datetime.now(timezone.utc) - self.last_heartbeat_time).total_seconds()
        
        if elapsed > self.heartbeat_timeout_seconds:
            self.logger.warning(
                f"[HelperMonitor] No heartbeat for {elapsed:.0f}s "
                f"(timeout: {self.heartbeat_timeout_seconds}s)"
            )
            return False
        
        return True
    
    def _attempt_restart(self, reason: str):
        """Attempt to restart Helper process"""
        # Check cooldown after max attempts
        if self.restart_attempts >= self.max_restart_attempts:
            if self.last_restart_time:
                elapsed = (datetime.now(timezone.utc) - self.last_restart_time).total_seconds()
                cooldown_seconds = self.restart_cooldown_minutes * 60
                
                if elapsed < cooldown_seconds:
                    remaining = int((cooldown_seconds - elapsed) / 60)
                    self.logger.debug(f"[HelperMonitor] In cooldown, {remaining} min remaining")
                    return
                else:
                    # Cooldown expired, reset counter
                    self.logger.info("[HelperMonitor] Cooldown expired, resetting attempts")
                    self.restart_attempts = 0
        
        self.restart_attempts += 1
        self.last_restart_time = datetime.now(timezone.utc)
        
        self.logger.warning(
            f"[HelperMonitor] RESTART ATTEMPT #{self.restart_attempts}/{self.max_restart_attempts}"
        )
        self.logger.warning(f"[HelperMonitor] Reason: {reason}")
        
        # Try to restart Helper
        success = self._restart_helper()
        
        if success:
            self.logger.info("[HelperMonitor] Helper restart initiated")
        else:
            self.logger.error("[HelperMonitor] Helper restart FAILED")
            
            # Check if we should enter degraded mode
            if self.restart_attempts >= self.max_restart_attempts:
                self._enter_degraded_mode(reason)
    
    def _restart_helper(self) -> bool:
        """Restart Helper via Task Scheduler"""
        try:
            # Method 1: Run the scheduled task
            result = subprocess.run(
                ['schtasks', '/run', '/tn', 'SentinelEdgeUserHelper'],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                self.logger.info("[HelperMonitor] Helper restarted via Task Scheduler")
                return True
            else:
                self.logger.warning(f"[HelperMonitor] schtasks failed: {result.stderr}")
                
        except subprocess.TimeoutExpired:
            self.logger.error("[HelperMonitor] schtasks timeout")
        except Exception as e:
            self.logger.error(f"[HelperMonitor] Restart error: {e}")
        
        return False
    
    def _enter_degraded_mode(self, reason: str):
        """Enter degraded mode after max restart attempts"""
        if self.operational_status == self.STATUS_DEGRADED:
            return  # Already in degraded mode
        
        self.logger.critical("=" * 70)
        self.logger.critical("[HelperMonitor] ENTERING DEGRADED MODE")
        self.logger.critical(f"[HelperMonitor] Reason: {reason}")
        self.logger.critical(f"[HelperMonitor] Failed {self.max_restart_attempts} restart attempts")
        self.logger.critical("=" * 70)
        
        self.operational_status = self.STATUS_DEGRADED
        self.status_reason = reason
        
        # Notify server
        self._notify_server_status(
            self.STATUS_DEGRADED,
            f"Helper failed after {self.max_restart_attempts} restart attempts: {reason}"
        )
    
    def _notify_server_status(self, status: str, reason: str):
        """Notify server of operational status change"""
        try:
            import urllib.request
            import urllib.error
            
            payload = {
                "agent_id": self.config.agent_id,
                "operational_status": status,
                "status_reason": reason,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "diagnostics": {
                    "restart_attempts": self.restart_attempts,
                    "helper_pid": self.helper_pid,
                    "last_heartbeat": self.last_heartbeat_time.isoformat() if self.last_heartbeat_time else None
                }
            }
            
            url = f"{self.config.server_url}/api/agent/status"
            headers = {
                "Content-Type": "application/json",
                "X-Agent-ID": self.config.agent_id,
                "Authorization": f"Bearer {self.config.api_key or self.config.api_token or ''}"
            }
            
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode(),
                headers=headers,
                method='POST'
            )
            
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status == 200:
                    self.logger.info(f"[HelperMonitor] Server notified: {status}")
                else:
                    self.logger.warning(f"[HelperMonitor] Server responded: {response.status}")
                    
        except urllib.error.URLError as e:
            self.logger.warning(f"[HelperMonitor] Could not notify server: {e}")
        except Exception as e:
            self.logger.error(f"[HelperMonitor] Notify error: {e}")
    
    def get_status(self) -> dict:
        """Get current Helper monitoring status"""
        return {
            "operational_status": self.operational_status,
            "status_reason": self.status_reason,
            "helper_pid": self.helper_pid,
            "last_heartbeat": self.last_heartbeat_time.isoformat() if self.last_heartbeat_time else None,
            "restart_attempts": self.restart_attempts
        }

class ManifestVerifier:
    """Verifies signed manifest for security with Phase-1 bypass"""
    
    def __init__(self, config: CoreConfig):
        self.config = config
        self.logger = logging.getLogger('ManifestVerifier')
    
    def verify_manifest(self) -> bool:
        """Verify manifest signature using bundled public key"""
        # Phase-1: Skip verification if flag is set
        if self.config.skip_manifest_verification:
            self.logger.warning("Manifest verification disabled by config flag")
            return True
        
        try:
            manifest_path = Path(__file__).parent / 'manifest.json'
            sig_path = Path(__file__).parent / 'manifest.sig'
            pub_key_path = Path(__file__).parent / 'public.pem'
            
            if not manifest_path.exists():
                self.logger.warning("No manifest.json found, skipping verification")
                return True
            
            if not sig_path.exists():
                self.logger.warning("No manifest.sig found, skipping verification")
                return True
            
            if not pub_key_path.exists():
                self.logger.warning("No public.pem found, skipping verification")
                return True
            
            # Read files
            manifest_data = manifest_path.read_bytes()
            signature_data = sig_path.read_bytes()
            public_key_data = pub_key_path.read_text()
            
            # Verify signature (simplified - in production, use cryptography library)
            try:
                from cryptography.hazmat.primitives import hashes
                from cryptography.hazmat.primitives.asymmetric import padding
                from cryptography.hazmat.primitives.serialization import load_pem_public_key
                from cryptography.exceptions import InvalidSignature
                
                # Load public key
                public_key = load_pem_public_key(public_key_data.encode())
                
                # Verify signature
                public_key.verify(
                    signature_data,
                    manifest_data,
                    padding.PSS(
                        mgf=padding.MGF1(hashes.SHA256()),
                        salt_length=padding.PSS.MAX_LENGTH
                    ),
                    hashes.SHA256()
                )
                
                self.logger.info("[OK] Manifest signature verified successfully")
                return True
                
            except ImportError:
                self.logger.warning("Cryptography library not available, skipping manifest verification")
                return True
            except InvalidSignature:
                self.logger.error("[FAIL] Invalid manifest signature detected!")
                return False
            except Exception as e:
                self.logger.error(f"Manifest verification error: {e}")
                return False
                
        except Exception as e:
            self.logger.error(f"Manifest verification failed: {e}")
            return False


class PowerEventMonitor:
    """Monitors Windows power events (sleep/wake)"""
    
    def __init__(self, callback):
        self.callback = callback
        self.logger = logging.getLogger('PowerMonitor')
        self.running = False
        self.thread = None
        
    def start(self):
        """Start monitoring power events"""
        if not HAS_WIN32:
            self.logger.warning("Power monitoring not available (pywin32 missing)")
            return
            
        self.running = True
        self.thread = Thread(target=self._monitor_loop, daemon=True)
        self.thread.start()
        self.logger.info("Power event monitoring started")
    
    def stop(self):
        """Stop monitoring"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
    
    def _monitor_loop(self):
        """Monitor loop using Windows messages"""
        try:
            # Create a hidden window to receive power messages
            wc = win32gui.WNDCLASS()
            wc.lpfnWndProc = self._wnd_proc
            wc.lpszClassName = 'SentinelEdgePowerMonitor'
            wc.hInstance = win32api.GetModuleHandle(None)
            
            class_atom = win32gui.RegisterClass(wc)
            hwnd = win32gui.CreateWindow(
                class_atom,
                'SentinelEdge Power Monitor',
                0, 0, 0, 0, 0, 0, 0,
                wc.hInstance,
                None
            )
            
            self.logger.info(f"Power monitor window created: {hwnd}")
            
            # Message loop
            while self.running:
                win32gui.PumpWaitingMessages()
                time.sleep(0.1)
                
        except Exception as e:
            self.logger.error(f"Power monitor error: {e}", exc_info=True)
    
    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        """Window procedure to handle power messages"""
        if msg == win32con.WM_POWERBROADCAST:
            if wparam == win32con.PBT_APMSUSPEND:
                self.logger.info("System entering sleep/suspend")
                self.callback('suspend')
            elif wparam == win32con.PBT_APMRESUMESUSPEND:
                self.logger.info("System resuming from sleep/suspend")
                self.callback('resume')
            elif wparam == win32con.PBT_APMRESUMEAUTOMATIC:
                self.logger.info("System auto-resume from sleep")
                self.callback('resume')
        
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)


class SentinelCore:
    """Main core service with enhanced security and Phase-1 flags"""
    
    def __init__(self):
        # Load configuration
        self.config = CoreConfig()
        
        # Setup logging
        self._setup_logging()
        
        # Verify manifest
        self.manifest_verifier = ManifestVerifier(self.config)
        if not self.manifest_verifier.verify_manifest():
            self.logger.error("[WARN] Manifest verification failed, auto-upgrade disabled")
            # Continue operation but disable auto-upgrade
            self.auto_upgrade_enabled = False
        else:
            self.auto_upgrade_enabled = True
        
        # Initialize components with config
        self.buffer = BufferDB(self.config.db_path)
        self.ingest_server = IngestServer(self.config, self.buffer)
        self.aggregator = HeartbeatAggregator(self.buffer, self.config)
        self.uploader = ServerUploader(self.config, self.buffer)
        
        # Initialize Live Telemetry Tracker
        # Works in parallel with Batch Uploads:
        # - Batch: Ensures historical history (Zero Data Loss)
        # - Live: Ensures accurate Daily Totals (active/idle/locked counters)
        self.live_telemetry = LiveTelemetryTracker(
            self.config, 
            self.buffer, 
            self.uploader
        )
        
        # Initialize Helper Monitor
        # Monitors Helper process health, auto-restarts, reports degraded mode
        install_dir = Path(__file__).parent.parent  # agent/core -> agent
        self.helper_monitor = HelperMonitor(self.config, self.uploader, install_dir)
        
        # Connect IngestServer heartbeat callback to HelperMonitor
        self.ingest_server.set_heartbeat_callback(self.helper_monitor.on_heartbeat_received)
        
        # Register config change callbacks
        self.config.register_change_callback(self._on_config_change)
        
        # State tracking
        self.is_suspended = False
        self.last_wake_time = datetime.now(timezone.utc)
        self.startup_time = datetime.now(timezone.utc)
        
        # Worker threads
        self.shutdown_event = Event()
        self.aggregator_thread = None
        self.uploader_thread = None
        self.health_check_thread = None
        self.config_reload_thread = None
        
        # Power management
        self.power_monitor = PowerEventMonitor(self._handle_power_event)
        
        self.logger.info("="*70)
        self.logger.info("SentinelEdge Core Service v2.1 - With Helper Monitoring")
        self.logger.info(f"Agent ID: {self.config.agent_id}")
        self.logger.info(f"Server URL: {self.config.server_url}")
        self.logger.info(f"Listening on: {self.config.listen_host}:{self.config.listen_port}")
        self.logger.info(f"Database: {self.config.db_path}")
        self.logger.info(f"Startup time: {self.startup_time.isoformat()}")
        self.logger.info(f"Manifest verified: {self.auto_upgrade_enabled}")
        self.logger.info(f"Registered: {self.config.is_registered()}")
        # Config-driven features
        self.logger.info(f"Ingest enabled: {self.config.enable_ingest}")
        self.logger.info(f"Aggregator enabled: {self.config.enable_aggregator}")
        self.logger.info(f"Uploader enabled: {self.config.enable_uploader}")
        self.logger.info(f"Dynamic reload: {self.config.dynamic_reload_enabled}")
        self.logger.info(f"Live Telemetry: DISABLED (Batch Mode Only)")
        self.logger.info("="*70)
        
    def _setup_logging(self):
        """Configure logging with rotation"""
        self.config.logs_dir.mkdir(parents=True, exist_ok=True)
        
        log_file = self.config.logs_dir / 'core.log'
        
        # Create formatter
        formatter = logging.Formatter(
            '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
        )
        
        # Get root logger and configure it directly
        # (basicConfig doesn't work if logging has already been used)
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)
        
        # Remove any existing handlers (clears default StreamHandler)
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
        
        # Console handler (for NSSM stderr capture)
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler.setLevel(logging.INFO)
        root_logger.addHandler(console_handler)
        
        # File handler
        try:
            from logging.handlers import RotatingFileHandler
            file_handler = RotatingFileHandler(
                log_file,
                maxBytes=10*1024*1024,  # 10MB
                backupCount=5,
                encoding='utf-8'
            )
            file_handler.setFormatter(formatter)
            file_handler.setLevel(logging.INFO)
            root_logger.addHandler(file_handler)
            print(f"[LOGGING] File handler created: {log_file}")
        except Exception as e:
            print(f"[LOGGING] Warning: Could not create file handler: {e}")
        
        self.logger = logging.getLogger('SentinelCore')
        self.logger.info(f"Logging configured - file: {log_file}")
        
    def _handle_power_event(self, event_type: str):
        """Handle power management events"""
        if event_type == 'suspend':
            self.logger.info("[PAUSE] System suspending - pausing operations")
            self.is_suspended = True
            
            # Flush any pending data
            try:
                self.logger.info("Flushing pending data before suspend...")
                self.aggregator.process_heartbeats()
                self.uploader.upload_batch()
            except Exception as e:
                self.logger.error(f"Error flushing data on suspend: {e}")
                
        elif event_type == 'resume':
            self.logger.info("[RESUME] System resumed - restarting operations")
            self.is_suspended = False
            self.last_wake_time = datetime.now(timezone.utc)
            
            # Re-register with server (in case of long sleep)
            try:
                if self.uploader.ensure_registered():
                    self.logger.info("[OK] Re-registered with server after resume")
            except Exception as e:
                self.logger.warning(f"Failed to re-register after resume: {e}")
    
    def _on_config_change(self, config: CoreConfig):
        """Handle configuration changes dynamically"""
        self.logger.info("=" * 70)
        self.logger.info("[CONFIG] Configuration changed - applying updates...")
        
        try:
            # Notify all components of config change
            self.aggregator.apply_config(config)
            self.uploader.apply_config(config)
            self.ingest_server.apply_config(config)
            
            self.logger.info("[CONFIG] All components updated successfully")
            self.logger.info("=" * 70)
            
        except Exception as e:
            self.logger.error(f"Error applying config changes: {e}", exc_info=True)
    
    def _config_reload_worker(self):
        """Worker thread for checking config file changes"""
        self.logger.info("Config reload worker running")
        
        while not self.shutdown_event.is_set():
            try:
                # Check for config changes
                if self.config.check_for_reload():
                    self.logger.info("[CONFIG] Config reloaded, changes applied")
                
                # Wait for next check
                self.shutdown_event.wait(self.config.dynamic_reload_interval)
                
            except Exception as e:
                self.logger.error(f"Config reload worker error: {e}", exc_info=True)
                self.shutdown_event.wait(60)  # Wait 1 minute before retry
        
        self.logger.info("Config reload worker stopped")
    
    def start(self):
        """Start all components with enhanced registration flow"""
        try:
            # Check for pending data from previous run
            self._check_pending_data()
            
            # Pass live_telemetry reference to ingest server BEFORE starting
            self.ingest_server.live_telemetry = self.live_telemetry
            
            # Start ingest server
            self.logger.info("Starting ingest server...")
            self.ingest_server.start()
            self.logger.info("[OK] Ingest server started (with live telemetry)")
            
            # ===================================================================
            # Enhanced Registration Flow with Detailed Logging
            # ===================================================================
            
            self.logger.info("=" * 70)
            self.logger.info("REGISTRATION CHECK")
            self.logger.info("=" * 70)
            
            # Check if already registered
            if self.config.api_key or self.config.api_token:
                self.logger.info("[REGISTRATION] API key found in configuration")
                self.logger.info(f"[REGISTRATION] API key: {(self.config.api_key or self.config.api_token)[:20]}...")
                self.logger.info("[REGISTRATION] Agent appears to be registered")
                
                # Verify with server
                self.logger.info("[REGISTRATION] Verifying registration with server...")
                if self.uploader.ensure_registered():
                    self.logger.info("=" * 70)
                    self.logger.info("[REGISTRATION] [OK] Registration verified successfully")
                    self.logger.info(f"[REGISTRATION] Agent ID: {self.config.agent_id}")
                    self.logger.info(f"[REGISTRATION] Server URL: {self.config.server_url}")
                    self.logger.info("=" * 70)
                else:
                    self.logger.warning("=" * 70)
                    self.logger.warning("[REGISTRATION] [WARN] Registration verification failed")
                    self.logger.warning("[REGISTRATION] Will attempt re-registration...")
                    self.logger.warning("=" * 70)
                    
                    # Try to re-register
                    registration_attempts = 0
                    max_attempts = 3
                    
                    while registration_attempts < max_attempts:
                        registration_attempts += 1
                        self.logger.info(f"[REGISTRATION] Re-registration attempt {registration_attempts}/{max_attempts}")
                        
                        if self.uploader.register():
                            self.logger.info("=" * 70)
                            self.logger.info("[REGISTRATION] [OK] Re-registration successful")
                            self.logger.info("=" * 70)
                            break
                        else:
                            self.logger.warning(f"[REGISTRATION] Attempt {registration_attempts} failed")
                            if registration_attempts < max_attempts:
                                self.logger.info("[REGISTRATION] Retrying in 5 seconds...")
                                time.sleep(5)
                    
                    if registration_attempts >= max_attempts:
                        self.logger.error("=" * 70)
                        self.logger.error("[REGISTRATION] [FAIL] Re-registration failed after all attempts")
                        self.logger.error("[REGISTRATION] Agent will continue but uploads may fail")
                        self.logger.error("[REGISTRATION] Will retry automatically during operation")
                        self.logger.error("=" * 70)
            else:
                # No API key - first time registration
                self.logger.info("[REGISTRATION] No API key found - first time setup")
                self.logger.info("[REGISTRATION] Starting registration process...")
                
                registration_attempts = 0
                max_attempts = 5
                
                while registration_attempts < max_attempts:
                    registration_attempts += 1
                    
                    self.logger.info("=" * 70)
                    self.logger.info(f"[REGISTRATION] Registration attempt {registration_attempts}/{max_attempts}")
                    self.logger.info(f"[REGISTRATION] Agent ID: {self.config.agent_id}")
                    self.logger.info(f"[REGISTRATION] Server URL: {self.config.server_url}")
                    self.logger.info("=" * 70)
                    
                    if self.uploader.register():
                        self.logger.info("=" * 70)
                        self.logger.info("[REGISTRATION] [OK][OK][OK] REGISTRATION SUCCESSFUL [OK][OK][OK]")
                        self.logger.info(f"[REGISTRATION] Agent {self.config.agent_id} is now registered")
                        if self.config.api_key:
                            self.logger.info(f"[REGISTRATION] API key: {self.config.api_key[:20]}...")
                        self.logger.info("[REGISTRATION] Configuration saved")
                        self.logger.info("=" * 70)
                        break
                    else:
                        self.logger.warning(f"[REGISTRATION] [FAIL] Attempt {registration_attempts} failed")
                        
                        if registration_attempts < max_attempts:
                            wait_time = min(5 * registration_attempts, 30)  # Exponential backoff
                            self.logger.info(f"[REGISTRATION] Retrying in {wait_time} seconds...")
                            time.sleep(wait_time)
                        else:
                            self.logger.error("=" * 70)
                            self.logger.error("[REGISTRATION] [FAIL][FAIL][FAIL] REGISTRATION FAILED [FAIL][FAIL][FAIL]")
                            self.logger.error(f"[REGISTRATION] Failed after {max_attempts} attempts")
                            self.logger.error("[REGISTRATION] Possible issues:")
                            self.logger.error("[REGISTRATION]   1. Server is not reachable")
                            self.logger.error("[REGISTRATION]   2. Server URL is incorrect")
                            self.logger.error("[REGISTRATION]   3. Network connectivity problems")
                            self.logger.error("[REGISTRATION]   4. Server registration endpoint not working")
                            self.logger.error("[REGISTRATION] Agent will continue but uploads will fail")
                            self.logger.error("[REGISTRATION] Will retry automatically during operation")
                            self.logger.error("=" * 70)
            
            # ===================================================================
            # End of Enhanced Registration Flow
            # ===================================================================
            
            # Start power monitoring
            self.power_monitor.start()
            
            # Start aggregator worker
            self.logger.info("Starting aggregator worker...")
            self.aggregator_thread = Thread(
                target=self._aggregator_worker,
                daemon=True,
                name="Aggregator"
            )
            self.aggregator_thread.start()
            self.logger.info("[OK] Aggregator worker started")
            
            # Start uploader worker
            self.logger.info("Starting uploader worker...")
            self.uploader_thread = Thread(
                target=self._uploader_worker,
                daemon=True,
                name="Uploader"
            )
            self.uploader_thread.start()
            self.logger.info("[OK] Uploader worker started")
            
            # Start health check worker
            self.logger.info("Starting health check worker...")
            self.health_check_thread = Thread(
                target=self._health_check_worker,
                daemon=True,
                name="HealthCheck"
            )
            self.health_check_thread.start()
            self.logger.info("[OK] Health check worker started")
            
            # Start config reload worker (if enabled)
            if self.config.dynamic_reload_enabled:
                self.logger.info("Starting config reload worker...")
                self.config_reload_thread = Thread(
                    target=self._config_reload_worker,
                    daemon=True,
                    name="ConfigReload"
                )
                self.config_reload_thread.start()
                self.logger.info("[OK] Config reload worker started")
            else:
                self.logger.info("Dynamic config reload disabled")
            
            # Start Helper Monitor
            self.logger.info("Starting Helper monitor...")
            self.helper_monitor.start()
            self.logger.info("[OK] Helper monitor started")
            
            self.logger.info("="*70)
            self.logger.info("[OK] All components started successfully!")
            self.logger.info("Core service is now running...")
            self.logger.info("="*70)
            
        except Exception as e:
            self.logger.error(f"Failed to start: {e}", exc_info=True)
            raise
    
    def _check_pending_data(self):
        """Check for pending data from previous run"""
        try:
            # Check unprocessed heartbeats
            unprocessed = self.buffer.get_unprocessed_heartbeats(limit=1)
            if unprocessed:
                self.logger.info(f"[DATA] Found pending heartbeats from previous run")
            
            # Check unuploaded events
            unuploaded = self.buffer.get_unuploaded_merged_events(limit=1)
            if unuploaded:
                self.logger.info(f"[UPLOAD] Found pending events to upload")
                
        except Exception as e:
            self.logger.error(f"Error checking pending data: {e}")
    
    def _aggregator_worker(self):
        """Worker thread for aggregating heartbeats"""
        self.logger.info("Aggregator worker running")
        
        consecutive_errors = 0
        max_consecutive_errors = 5
        
        # Cleanup tracking - run once per day (24 hours)
        CLEANUP_INTERVAL = 86400  # 24 hours in seconds
        last_cleanup = time.time()
        
        while not self.shutdown_event.is_set():
            try:
                # Skip processing if suspended
                if self.is_suspended:
                    self.shutdown_event.wait(10)
                    continue
                
                # Process heartbeats
                self.aggregator.process_heartbeats()
                consecutive_errors = 0  # Reset on success
                
                # Periodic buffer cleanup (once per day)
                current_time = time.time()
                if current_time - last_cleanup > CLEANUP_INTERVAL:
                    try:
                        self.logger.info("[CLEANUP] Starting daily buffer cleanup...")
                        deleted = self.buffer.cleanup_uploaded_data(retention_days=7)
                        last_cleanup = current_time
                    except Exception as e:
                        self.logger.error(f"[CLEANUP] Cleanup error (non-critical): {e}")
                
                # Sleep for aggregation interval
                self.shutdown_event.wait(self.config.aggregation_interval)
                
            except Exception as e:
                consecutive_errors += 1
                self.logger.error(
                    f"Aggregator error ({consecutive_errors}/{max_consecutive_errors}): {e}",
                    exc_info=True
                )
                
                if consecutive_errors >= max_consecutive_errors:
                    self.logger.critical("Aggregator worker failing repeatedly, increasing retry interval")
                    self.shutdown_event.wait(300)  # Wait 5 minutes
                    consecutive_errors = 0
                else:
                    self.shutdown_event.wait(60)  # Wait 1 minute before retry
        
        self.logger.info("Aggregator worker stopped")
    
    def _uploader_worker(self):
        """Worker thread for uploading to server"""
        self.logger.info("Uploader worker running")
        
        # Wait a bit for initial data to accumulate
        self.shutdown_event.wait(30)
        
        consecutive_errors = 0
        max_consecutive_errors = 5
        
        while not self.shutdown_event.is_set():
            try:
                # Skip uploading if suspended
                if self.is_suspended:
                    self.shutdown_event.wait(10)
                    continue
                
                # Upload batch
                self.uploader.upload_batch()
                consecutive_errors = 0  # Reset on success
                
                # Sleep for upload interval
                self.shutdown_event.wait(self.config.upload_interval)
                
            except Exception as e:
                consecutive_errors += 1
                self.logger.error(
                    f"Uploader error ({consecutive_errors}/{max_consecutive_errors}): {e}",
                    exc_info=True
                )
                
                if consecutive_errors >= max_consecutive_errors:
                    self.logger.critical("Uploader worker failing repeatedly, increasing retry interval")
                    self.shutdown_event.wait(300)  # Wait 5 minutes
                    consecutive_errors = 0
                else:
                    self.shutdown_event.wait(60)  # Wait 1 minute before retry
        
        self.logger.info("Uploader worker stopped")
    
    def _health_check_worker(self):
        """Worker thread for periodic health checks with API key verification"""
        self.logger.info("Health check worker running")
        
        while not self.shutdown_event.is_set():
            try:
                # Wait 2 minutes between checks
                self.shutdown_event.wait(120)
                
                if self.is_suspended:
                    continue
                
                # Log runtime statistics
                uptime = (datetime.now(timezone.utc) - self.startup_time).total_seconds()
                hours = int(uptime / 3600)
                minutes = int((uptime % 3600) / 60)
                
                self.logger.info("=" * 70)
                self.logger.info(f"[HEALTH] Health check - Uptime: {hours}h {minutes}m")
                
                # Check database size
                if self.config.db_path.exists():
                    db_size_mb = self.config.db_path.stat().st_size / (1024 * 1024)
                    self.logger.info(f"[HEALTH] Database size: {db_size_mb:.2f} MB")
                
                # Check registration status
                if self.config.is_registered():
                    api_key = self.config.api_key or self.config.api_token
                    self.logger.info(f"[HEALTH] Registration: [OK] Active")
                    if api_key:
                        self.logger.info(f"[HEALTH] API Key: {api_key[:20]}...")
                else:
                    self.logger.warning("[HEALTH] Registration: [FAIL] Not registered")
                    self.logger.warning("[HEALTH] Attempting registration...")
                    if self.uploader.register():
                        self.logger.info("[HEALTH] [OK] Registration successful")
                    else:
                        self.logger.error("[HEALTH] [FAIL] Registration failed")
                
                # Verify server connectivity
                if self.uploader.ensure_registered():
                    self.logger.info("[HEALTH] Server connection: [OK] OK")
                else:
                    self.logger.warning("[HEALTH] Server connection: [FAIL] Failed")
                
                self.logger.info("=" * 70)
                    
            except Exception as e:
                self.logger.error(f"Health check error: {e}")
        
        self.logger.info("Health check worker stopped")
    
    def run(self):
        """Run the service"""
        try:
            self.start()
            
            # Keep running until shutdown signal
            self.logger.info("Service is running. Press Ctrl+C to stop.")
            while not self.shutdown_event.is_set():
                self.shutdown_event.wait(1)
                
        except KeyboardInterrupt:
            self.logger.info("Shutdown requested via Ctrl+C")
        except Exception as e:
            self.logger.error(f"Fatal error: {e}", exc_info=True)
        finally:
            self.stop()
    
    def stop(self):
        """Stop the service gracefully"""
        self.logger.info("Stopping core service...")
        
        # Signal shutdown
        self.shutdown_event.set()
        
        # Stop Helper monitoring
        self.helper_monitor.stop()
        
        # Stop power monitoring
        self.power_monitor.stop()
        
        # Stop ingest server
        self.ingest_server.stop()
        
        # Final data flush
        try:
            self.logger.info("Flushing final data...")
            
            # Note: live_telemetry doesn't need explicit flush - 
            # data is already sent in real-time via process_heartbeat()
            
            # Flush aggregator and uploader
            self.aggregator.process_heartbeats()
            self.uploader.upload_batch()
        except Exception as e:
            self.logger.error(f"Error during final flush: {e}")
        
        # Close database connection
        try:
            self.buffer.close()
            self.logger.info("Database connection closed")
        except Exception as e:
            self.logger.error(f"Error closing database: {e}")
        
        # Wait for workers
        threads = [
            (self.aggregator_thread, "Aggregator"),
            (self.uploader_thread, "Uploader"),
            (self.health_check_thread, "HealthCheck"),
            (self.config_reload_thread, "ConfigReload")
        ]
        
        for thread, name in threads:
            if thread and thread.is_alive():
                self.logger.info(f"Waiting for {name} worker...")
                thread.join(timeout=10)
                if thread.is_alive():
                    self.logger.warning(f"{name} worker did not stop gracefully")
        
        self.logger.info("="*70)
        self.logger.info("Core service stopped cleanly")
        self.logger.info("="*70)


def main():
    """Entry point"""
    core = SentinelCore()
    core.run()


if __name__ == '__main__':
    main()
