"""
Helper Configuration Module - Config-Driven v2
Uses unified config schema with dynamic reload
"""
import os
import json
import hashlib
import logging
import time
from pathlib import Path
from typing import Dict, Any, Optional, Callable
from threading import Lock
import sys

# Import config schema from core
sys.path.insert(0, str(Path(__file__).parent.parent))
from core.config_schema import load_and_validate_config, ConfigValidator

class HelperConfig:
    """Helper configuration - fully config-driven with dynamic reload"""
    
    def __init__(self, config_path: str = None):
        self.logger = logging.getLogger('HelperConfig')
        
        # Use shared config file in ProgramData
        self.config_path = Path(config_path or self._get_default_config_path())
        
        # Thread-safe config updates
        self._config_lock =Lock()
        
        # Track file modification for reload detection
        self._last_mtime = 0
        self._last_checksum = ""
        
        # Last known good config (fallback)
        self._last_good_config = None
        
        # Config change callbacks
        self._change_callbacks: list[Callable] = []
        
        # Paths
        self.data_dir = Path(os.environ.get('APPDATA', '.')) / 'SentinelEdge'
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir = self.data_dir  # Alias for compatibility
        self.state_file = self.data_dir / 'helper_state.json'
        self.log_file = self.data_dir / 'helper.log'
        
        # Load and validate config
        self._load_and_apply_config()
    
    def _get_default_config_path(self) -> str:
        """Get default config path (shared with Core)"""
        program_data = os.environ.get('ProgramData', r'C:\ProgramData')
        return str(Path(program_data) / 'SentinelEdge' / 'config.json')
    
    def _load_and_apply_config(self):
        """Load, validate, and apply configuration"""
        with self._config_lock:
            # Load and validate
            validated_config, errors = load_and_validate_config(self.config_path)
            
            if validated_config is None:
                self.logger.error(f"Config validation failed: {errors}")
                if self._last_good_config:
                    self.logger.warning("Using last known good config")
                    validated_config = self._last_good_config
                else:
                    self.logger.warning("No last known good config, using defaults")
                    validator = ConfigValidator()
                    validated_config = validator.get_default_config()
            
            # Store as last known good
            self._last_good_config = validated_config
            
            # Apply config to attributes
            self._apply_config_to_attributes(validated_config)
            
            # Update file tracking
            if self.config_path.exists():
                self._last_mtime = self.config_path.stat().st_mtime
                with open(self.config_path, 'rb') as f:
                    self._last_checksum = hashlib.sha256(f.read()).hexdigest()
    
    def _apply_config_to_attributes(self, config: Dict[str, Any]):
        """Apply validated config to class attributes"""
        # Store full config
        self.config = config
        
        # Agent settings (synced from Core, DO NOT auto-generate)
        agent = config.get("agent", {})
        self.agent_id = agent.get("agent_id", "pending")
        self.local_agent_key = agent.get("local_agent_key", "pending")
        
        # Get Windows username for telemetry attribution
        import os
        import getpass
        try:
            domain = os.environ.get('USERDOMAIN', 'LOCAL')
            user = getpass.getuser()
            self.username = f"{domain}\\{user}"
        except Exception as e:
            self.logger.warning(f"Failed to get full username: {e}")
            self.username = os.environ.get('USERNAME', 'unknown')
        
        # Server settings (for reference)
        server = config.get("server", {})
        self.allow_insecure_http = server.get("allow_insecure_http", False)
        self.skip_cert_pinning = self.allow_insecure_http  # Same meaning
        self.skip_manifest_verification = server.get("skip_manifest_verification", False)
        
        # Legacy
        self.local_mode = config.get("local_mode", False)
        
        # Core communication
        core = config.get("core", {})
        core_port = core.get("listen_port", 48123)
        self.core_url = f'http://localhost:{core_port}'
        self.core_host = '127.0.0.1'
        self.core_port = core_port
        
        # Helper settings
        helper = config.get("helper", {})
        self.sample_interval = helper.get("heartbeat_interval", 10)
        self.heartbeat_interval = helper.get("heartbeat_interval", 10)
        self.domain_interval = helper.get("domain_interval", 60)
        self.inventory_interval = helper.get("inventory_interval", 3600)
        
        # Helper features
        features = helper.get("features", {})
        # NOTE: capture_window_titles MUST be True for domain tracking to work
        self.capture_window_titles = features.get("capture_window_titles", True)
        self.capture_full_urls = features.get("capture_full_urls", False)
        self.enable_domains = features.get("enable_domains", True)
        self.enable_inventory = features.get("enable_inventory", True)
        self.enable_app_tracking = features.get("enable_app_tracking", True)
        self.enable_idle_tracking = features.get("enable_idle_tracking", True)
        self.enable_app_specific_thresholds = features.get("enable_app_specific_thresholds", False)
        
        # Thresholds
        thresholds = config.get("thresholds", {})
        self.idle_threshold = thresholds.get("idle_seconds", 120)
        
        # Dynamic reload settings
        dynamic_reload = config.get("dynamic_reload", {})
        self.dynamic_reload_enabled = dynamic_reload.get("enabled", True)
        self.dynamic_reload_interval = dynamic_reload.get("check_interval", 30)
        
        # Window polling and fallback settings
        self.window_poll_interval = helper.get("window_poll_interval", 2)  # Default 2 seconds
        self.enable_cpu_fallback = helper.get("enable_cpu_fallback", True)  # Enable CPU fallback when window tracking fails
        
        self.logger.info("[CONFIG] Helper configuration applied successfully")
        self.logger.info(f"[CONFIG] Features: idle={self.enable_idle_tracking}, app={self.enable_app_tracking}, domains={self.enable_domains}, inventory={self.enable_inventory}")
    
    def check_for_reload(self) -> bool:
        """
        Check if config file has changed and reload if needed.
        Returns True if config was reloaded.
        """
        if not self.dynamic_reload_enabled:
            return False
        
        try:
            if not self.config_path.exists():
                return False
            
            # Check modification time
            current_mtime = self.config_path.stat().st_mtime
            if current_mtime == self._last_mtime:
                return False
            
            # Calculate checksum to confirm actual change
            with open(self.config_path, 'rb') as f:
                current_checksum = hashlib.sha256(f.read()).hexdigest()
            
            if current_checksum == self._last_checksum:
                # Content unchanged, but update mtime to avoid rechecking
                self._last_mtime = current_mtime
                return False
            
            # Config has changed - reload it
            self.logger.info("[CONFIG] Config file changed, reloading...")
            self._load_and_apply_config()
            
            # Notify callbacks
            self._notify_config_change()
            
            self.logger.info("[CONFIG] Config reload complete")
            return True
            
        except Exception as e:
            self.logger.error(f"Error checking for config reload: {e}")
            return False
    
    def register_change_callback(self, callback: Callable):
        """Register a callback to be notified of config changes"""
        self._change_callbacks.append(callback)
    
    def _notify_config_change(self):
        """Notify all registered callbacks of config change"""
        for callback in self._change_callbacks:
            try:
                callback(self)
            except Exception as e:
                self.logger.error(f"Error in config change callback: {e}")
    
    def save_config(self):
        """
        DISABLED: Helper should NEVER write to system config.json
        
        The config file is at C:\\ProgramData\\SentinelEdge\\config.json
        which is owned by SYSTEM/Administrators. Helper runs under user
        context and does not have permission to write there.
        
        Core manages config.json. Helper manages identity.json in AppData.
        """
        self.logger.warning(
            "[CONFIG] save_config() called but Helper cannot write to system config. "
            "This is intentional - only Core manages config.json."
        )
    
    def get_hmac_key(self) -> bytes:
        """Get HMAC key as bytes"""
        return self.local_agent_key.encode('utf-8')