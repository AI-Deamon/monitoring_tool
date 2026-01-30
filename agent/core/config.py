"""
Core Service Configuration Module - Config-Driven v2
Fully config-driven with schema validation and dynamic reload support
"""
import os
import json
import uuid
import hashlib
import logging
import time
import platform
from pathlib import Path
from typing import Dict, Any, Optional, Callable
from threading import Lock

from .secure_store import get_secure_storage
from .config_schema import load_and_validate_config, ConfigValidator

class CoreConfig:
    """Core service configuration - fully config-driven with dynamic reload"""
    
    def __init__(self, config_path: str = None):
        self.config_path = Path(config_path or self._get_default_config_path())
        self.logger = logging.getLogger('CoreConfig')
        
        # Define paths using environment variable for flexibility
        # Try ProgramData first (requires admin), fallback to user's LocalAppData
        self.data_dir = self._get_writable_data_dir()
        self.logs_dir = self.data_dir / 'logs'
        self.buffer_dir = self.data_dir / 'buffer'
        self.db_path = self.buffer_dir / 'core_buffer.db'
        
        # Thread-safe config updates
        self._config_lock = Lock()
        
        # Track file modification for reload detection
        self._last_mtime = 0
        self._last_checksum = ""
        
        # Last known good config (fallback)
        self._last_good_config = None
        
        # Config change callbacks
        self._change_callbacks: list[Callable] = []
        
        # Initialize secure storage (Base64 only - no DPAPI)
        self.secure_storage = get_secure_storage()
        
        # Load and validate config
        self._load_and_apply_config()
        
        # Ensure agent ID file exists
        self.ensure_agent_id_file()
    
    def _get_writable_data_dir(self) -> Path:
        """
        Get a writable data directory with intelligent fallback.
        Tries ProgramData (admin) first, falls back to LocalAppData (user).
        """
        # Option 1: Check if SENTINELEDGE_DATA_DIR is set (explicit override)
        env_data_dir = os.environ.get('SENTINELEDGE_DATA_DIR')
        if env_data_dir:
            data_dir = Path(env_data_dir)
            if self._is_dir_writable(data_dir):
                return data_dir
        
        # Option 2: Try ProgramData (requires admin rights)
        program_data = os.environ.get('ProgramData', r'C:\ProgramData')
        admin_dir = Path(program_data) / 'SentinelEdge'
        if self._is_dir_writable(admin_dir):
            return admin_dir
        
        # Option 3: Fallback to user's LocalAppData (no admin required)
        local_app_data = os.environ.get('LOCALAPPDATA')
        if local_app_data:
            user_dir = Path(local_app_data) / 'SentinelEdge'
            try:
                user_dir.mkdir(parents=True, exist_ok=True)
                if self._is_dir_writable(user_dir):
                    logging.getLogger('CoreConfig').info(
                        f"[CONFIG] Using user directory (no admin): {user_dir}"
                    )
                    return user_dir
            except Exception:
                pass
        
        # Option 4: Ultimate fallback to home directory
        home_dir = Path.home() / '.sentineledge'
        home_dir.mkdir(parents=True, exist_ok=True)
        logging.getLogger('CoreConfig').warning(
            f"[CONFIG] Using home fallback directory: {home_dir}"
        )
        return home_dir
    
    def _is_dir_writable(self, path: Path) -> bool:
        """Check if directory is writable (create test file)"""
        try:
            path.mkdir(parents=True, exist_ok=True)
            test_file = path / '.write_test'
            test_file.write_text('test')
            test_file.unlink()
            return True
        except (PermissionError, OSError):
            return False
        except Exception:
            return False
    
    def _get_default_config_path(self) -> str:
        """Get default config path - tries admin location first, then user location"""
        # Check if config exists in admin location
        program_data = os.environ.get('ProgramData', r'C:\ProgramData')
        admin_config = Path(program_data) / 'SentinelEdge' / 'config.json'
        if admin_config.exists():
            return str(admin_config)
        
        # Check user location
        local_app_data = os.environ.get('LOCALAPPDATA')
        if local_app_data:
            user_config = Path(local_app_data) / 'SentinelEdge' / 'config.json'
            if user_config.exists():
                return str(user_config)
        
        # Default to admin location (installer will create it)
        return str(admin_config)
    
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
        
        # Agent settings
        agent = config.get("agent", {})
        self.agent_id = agent.get("agent_id", "") or self._load_authoritative_agent_id()
        self.local_agent_key = agent.get("local_agent_key", "") or self._load_authoritative_agent_key()
        self.agent_name = agent.get("agent_name", "") or platform.node()  # Custom name, defaults to hostname
        
        # Update config if agent_id was loaded from file
        if not agent.get("agent_id"):
            config["agent"]["agent_id"] = self.agent_id
        if not agent.get("local_agent_key"):
            config["agent"]["local_agent_key"] = self.local_agent_key
        if not agent.get("agent_name"):
            config["agent"]["agent_name"] = self.agent_name
        
        # Server settings (with fallback to root-level for v1 compatibility)
        server = config.get("server", {})
        # Check nested first, then fallback to root-level (v1 format)
        self.server_url = server.get("url") or config.get("server_url") or "http://localhost:5050"
        self.registration_secret = server.get("registration_secret") or config.get("registration_secret", "")  # SEC-002
        self.server_cert_fingerprint = server.get("cert_pinning_fingerprint", "")
        self.allow_insecure_http = server.get("allow_insecure_http", False)
        self.skip_manifest_verification = server.get("skip_manifest_verification", False)
        
        # Legacy flags
        self.skip_cert_pinning = self.allow_insecure_http  # Same meaning
        self.local_mode = config.get("local_mode", False)  # Deprecated
        
        # Core settings
        core = config.get("core", {})
        self.listen_host = 'localhost'
        self.listen_port = core.get("listen_port", 48123)
        self.aggregation_interval = core.get("aggregation_interval", 60)
        self.upload_interval = core.get("upload_interval", 60)
        self.heartbeat_interval = core.get("heartbeat_interval", 60)
        self.enable_ingest = core.get("enable_ingest", True)
        self.enable_uploader = core.get("enable_uploader", True)
        self.enable_aggregator = core.get("enable_aggregator", True)
        
        # Helper settings (for reference/sharing)
        helper = config.get("helper", {})
        self.helper_config = helper
        
        # Thresholds
        thresholds = config.get("thresholds", {})
        self.idle_threshold = thresholds.get("idle_seconds", 120)
        
        # Retry settings
        retry = config.get("retry", {})
        self.max_retry_attempts = retry.get("max_attempts", 5)
        self.initial_backoff = retry.get("initial_backoff_seconds", 2)
        self.max_backoff = retry.get("max_backoff_seconds", 300)
        
        # Registration retry settings - Modified for local_mode
        if self.local_mode:
            self.max_registration_attempts = float('inf')  # Infinite retries
            self.registration_backoff_minutes = 0.083  # 5 seconds
        else:
            self.max_registration_attempts = 5
            self.registration_backoff_minutes = 30
        
        # Dynamic reload settings
        dynamic_reload = config.get("dynamic_reload", {})
        self.dynamic_reload_enabled = dynamic_reload.get("enabled", True)
        self.dynamic_reload_interval = dynamic_reload.get("check_interval", 30)
        
        # Paths - use writable directory (handles admin/non-admin)
        self.data_dir = self._get_writable_data_dir()
        self.state_dir = self.data_dir / 'state'
        self.buffer_dir = self.data_dir / 'buffer'
        self.logs_dir = self.data_dir / 'logs'
        
        # Ensure directories exist with proper error handling
        for dir_path in [self.state_dir, self.buffer_dir, self.logs_dir]:
            try:
                dir_path.mkdir(parents=True, exist_ok=True)
            except PermissionError:
                self.logger.error(f"[CONFIG] Cannot create directory: {dir_path}")
            except Exception as e:
                self.logger.warning(f"[CONFIG] Directory creation warning: {dir_path} - {e}")
        
        # Database
        self.db_path = self.buffer_dir / 'core_buffer.db'
        
        # Handle both api_key and api_token (backward compatibility)
        self.api_key = config.get("api_key", "")
        self.api_token = config.get("api_token", "") or self.api_key
        
        # Secure token handling
        self._init_api_token()
        
        self.logger.info("[CONFIG] Configuration applied successfully")
    
    def _init_api_token(self):
        """Initialize API token/key from secure storage with fallbacks"""
        # Try loading from secure storage first
        if self.secure_storage:
            token = self.secure_storage.load_token_securely(str(self.config_path))
            if token:
                self.logger.debug(f"[CONFIG] Loaded API key from secure storage: {token[:10]}...")
                self.api_token = token
                self.api_key = token  # Set both attributes
                return
        
        # Fallback to config.json - try api_key first, then api_token
        api_key = self.config.get('api_key', '')
        api_token = self.config.get('api_token', '')
        
        # Use whichever is present
        token = api_key or api_token
        
        if token:
            self.logger.debug(f"[CONFIG] Loaded API key from config.json: {token[:10]}...")
            self.api_token = token
            self.api_key = token
            return
        
        # No token available
        self.logger.warning("[CONFIG] No API key found - agent needs registration")
        self.api_token = ''
        self.api_key = ''
    
    def _load_authoritative_agent_id(self) -> str:
        """Load agent_id from authoritative source (Core is single source of truth)"""
        try:
            # Priority 1: Persistent agent_id file
            agent_id_file = self.data_dir / 'agent_id'
            if agent_id_file.exists():
                agent_id = agent_id_file.read_text().strip()
                if agent_id:
                    return agent_id
            
            # Priority 2: Generate new one only if no file exists
            new_id = str(uuid.uuid4())
            agent_id_file.parent.mkdir(parents=True, exist_ok=True)
            agent_id_file.write_text(new_id)
            return new_id
        except Exception as e:
            self.logger.error(f"Error loading authoritative agent_id: {e}")
            return str(uuid.uuid4())
    
    def _load_authoritative_agent_key(self) -> str:
        """
        Load local_agent_key from authoritative source.
        MUST NEVER return blank or whitespace.
        If missing, generates a new 256-bit key and saves it to config.json.
        """
        try:
            # Priority 1: Check config.json for existing key
            existing_key = self.config.get("agent", {}).get("local_agent_key", "")
            
            # Validate the key is not blank/whitespace
            if existing_key and existing_key.strip():
                return existing_key.strip()
            
            # Priority 2: Generate new 256-bit key
            self.logger.warning("[CONFIG] local_agent_key missing or blank - generating new key")
            new_key = hashlib.sha256(str(uuid.uuid4()).encode()).hexdigest()
            
            # Save to config immediately
            if "agent" not in self.config:
                self.config["agent"] = {}
            self.config["agent"]["local_agent_key"] = new_key
            
            # Write to config.json
            self._save_config_with_key(new_key)
            
            return new_key
            
        except Exception as e:
            self.logger.error(f"Error loading authoritative agent_key: {e}")
            # Fallback: generate and return (but not saved)
            return hashlib.sha256(str(uuid.uuid4()).encode()).hexdigest()
    
    def _save_config_with_key(self, key: str):
        """Save config.json with the new local_agent_key"""
        try:
            if self.config_path.exists():
                with open(self.config_path, 'r') as f:
                    config_data = json.load(f)
            else:
                config_data = {}
            
            if "agent" not in config_data:
                config_data["agent"] = {}
            
            config_data["agent"]["local_agent_key"] = key
            
            # Remove api_key if present (should NOT be in config.json)
            if "api_key" in config_data:
                del config_data["api_key"]
            
            # Write atomically
            temp_path = self.config_path.with_suffix('.tmp')
            with open(temp_path, 'w') as f:
                json.dump(config_data, f, indent=2)
            temp_path.replace(self.config_path)
            
            self.logger.info("[CONFIG] Saved local_agent_key to config.json")
            
        except Exception as e:
            self.logger.error(f"Error saving config with key: {e}")
    
    def ensure_agent_id_file(self):
        """Ensure agent_id file exists in ProgramData"""
        try:
            agent_id_file = self.data_dir / 'agent_id'
            agent_id_file.parent.mkdir(parents=True, exist_ok=True)
            
            if not agent_id_file.exists():
                agent_id_file.write_text(self.agent_id)
            else:
                # Read existing file to ensure consistency
                existing_id = agent_id_file.read_text().strip()
                if existing_id and existing_id != self.agent_id:
                    self.logger.warning(f"Agent ID mismatch, using file version: {existing_id}")
                    self.agent_id = existing_id
                    self.config["agent"]["agent_id"] = existing_id
        except Exception as e:
            self.logger.error(f"Error ensuring agent_id file: {e}")
    
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
        """Save current configuration"""
        try:
            with self._config_lock:
                # Update agent section
                self.config["agent"]["agent_id"] = self.agent_id
                self.config["agent"]["local_agent_key"] = self.local_agent_key
                
                # Store token securely if available
                if self.api_token and self.secure_storage:
                    self.secure_storage.store_token_securely(self.api_token, str(self.config_path))
                else:
                    self.config['api_token'] = self.api_token
                
                self.config['api_key'] = self.api_key
                
                with open(self.config_path, 'w') as f:
                    json.dump(self.config, f, indent=2)
                
                # Update tracking
                self._last_mtime = self.config_path.stat().st_mtime
                with open(self.config_path, 'rb') as f:
                    self._last_checksum = hashlib.sha256(f.read()).hexdigest()
                
                # Also ensure agent_id file exists
                self.ensure_agent_id_file()
                
        except Exception as e:
            self.logger.error(f"Error saving config: {e}")
    
    def is_registered(self) -> bool:
        """Check if agent is registered (has valid API key)"""
        # Check both api_token and api_key
        has_token = bool(self.api_token and self.api_token.strip())
        has_key = bool(self.api_key and self.api_key.strip())
        
        is_registered = has_token or has_key
        
        if is_registered:
            self.logger.debug(f"[CONFIG] Agent is registered (API key: {(self.api_key or self.api_token)[:10]}...)")
        else:
            self.logger.debug("[CONFIG] Agent is NOT registered (no API key)")
        
        return is_registered
    
    def clear_registration(self):
        """Clear registration data for re-registration"""
        self.logger.warning("[CONFIG] Clearing registration data...")
        
        self.api_token = ''
        self.api_key = ''
        
        if self.secure_storage:
            self.secure_storage.clear_secure_token(str(self.config_path))
            self.logger.info("[CONFIG] Cleared API key from secure storage")
        else:
            self.config['api_token'] = ''
            self.config['api_key'] = ''
            self.save_config()
            self.logger.info("[CONFIG] Cleared API key from config.json")
    
    def set_agent_id(self, new_id: str):
        """
        Set agent ID explicitly (called when server assigns a different identity).
        Updates both memory state and the authoritative file on disk atomically.
        
        This is used when the server assigns an existing agent ID based on hostname
        matching, and the agent needs to adopt that ID to maintain history.
        """
        if not new_id or new_id == self.agent_id:
            return
        
        with self._config_lock:
            old_id = self.agent_id
            self.logger.info(f"[CONFIG] Updating Agent ID: {old_id} -> {new_id}")
            
            # Update in-memory state
            self.agent_id = new_id
            if "agent" not in self.config:
                self.config["agent"] = {}
            self.config["agent"]["agent_id"] = new_id
            
            # Update authoritative file on disk FIRST
            # This prevents ensure_agent_id_file() from reverting to the old ID
            try:
                agent_id_file = self.data_dir / 'agent_id'
                agent_id_file.write_text(new_id)
                self.logger.info(f"[CONFIG] Updated authoritative agent_id file")
            except Exception as e:
                self.logger.error(f"[CONFIG] Failed to update agent_id file: {e}")
                # Revert memory state on failure
                self.agent_id = old_id
                self.config["agent"]["agent_id"] = old_id
                raise
    
    def get_hmac_key(self) -> bytes:
        """Get HMAC key as bytes"""
        return self.local_agent_key.encode('utf-8')
    
    def get_server_cert_fingerprint(self) -> str:
        """Get server certificate fingerprint for pinning"""
        return self.server_cert_fingerprint
    
    def set_server_cert_fingerprint(self, fingerprint: str):
        """Set server certificate fingerprint"""
        with self._config_lock:
            self.server_cert_fingerprint = fingerprint
            self.config["server"]["cert_pinning_fingerprint"] = fingerprint
            self.save_config()