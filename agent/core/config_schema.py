"""
SentinelEdge Unified Configuration Schema
Validates and migrates configuration files
"""
import json
import logging
from typing import Dict, Any, Optional, Tuple
from pathlib import Path

logger = logging.getLogger(__name__)

# Schema version 2 definition
CONFIG_SCHEMA_V2 = {
    "version": {
        "type": int,
        "required": True,
        "default": 2
    },
    "agent": {
        "type": dict,
        "required": True,
        "fields": {
            "agent_id": {"type": str, "required": True, "default": ""},
            "agent_name": {"type": str, "required": False, "default": ""},  # Custom display name
            "local_agent_key": {"type": str, "required": True, "default": ""}
        }
    },
    # Authentication section - populated after registration
    "authentication": {
        "type": dict,
        "required": False,
        "fields": {
            "api_key": {"type": str, "required": False, "default": ""},
            "api_key_stored_securely": {"type": bool, "required": False, "default": False},
            "registered": {"type": bool, "required": False, "default": False}
        }
    },
    "server": {
        "type": dict,
        "required": True,
        "fields": {
            "url": {"type": str, "required": True, "default": "http://localhost:5050"},
            "registration_secret": {"type": str, "required": False, "default": ""},  # SEC-002: Required for production
            "cert_pinning_fingerprint": {"type": str, "required": False, "default": ""},
            "allow_insecure_http": {"type": bool, "required": False, "default": False},
            "skip_manifest_verification": {"type": bool, "required": False, "default": False}
        }
    },
    "core": {
        "type": dict,
        "required": True,
        "fields": {
            "listen_port": {"type": int, "required": True, "default": 48123, "min": 1024, "max": 65535},
            "aggregation_interval": {"type": int, "required": True, "default": 60, "min": 10},
            "upload_interval": {"type": int, "required": True, "default": 60, "min": 10},
            "heartbeat_interval": {"type": int, "required": True, "default": 60, "min": 10},
            "enable_ingest": {"type": bool, "required": True, "default": True},
            "enable_uploader": {"type": bool, "required": True, "default": True},
            "enable_aggregator": {"type": bool, "required": True, "default": True}
        }
    },
    "helper": {
        "type": dict,
        "required": True,
        "fields": {
            "heartbeat_interval": {"type": int, "required": True, "default": 10, "min": 5},
            "domain_interval": {"type": int, "required": True, "default": 60, "min": 10},
            "inventory_interval": {"type": int, "required": True, "default": 3600, "min": 60},
            "features": {
                "type": dict,
                "required": True,
                "fields": {
                    "capture_window_titles": {"type": bool, "required": True, "default": True},
                    "capture_full_urls": {"type": bool, "required": True, "default": False},
                    "enable_domains": {"type": bool, "required": True, "default": True},
                    "enable_inventory": {"type": bool, "required": True, "default": True},
                    "enable_app_tracking": {"type": bool, "required": True, "default": True},
                    "enable_idle_tracking": {"type": bool, "required": True, "default": True},
                    "enable_app_specific_thresholds": {"type": bool, "required": False, "default": False}
                }
            }
        }
    },
    "thresholds": {
        "type": dict,
        "required": True,
        "fields": {
            "idle_seconds": {"type": int, "required": True, "default": 120, "min": 30},
            # EDGE CASE FIX: App-specific idle thresholds
            # Keys are lowercase app names (e.g., "vlc.exe", "teams.exe")
            # Values are idle threshold in seconds
            "app_specific": {
                "type": dict,
                "required": False,
                "default": {},
                "description": "Custom idle thresholds per app (e.g., {'vlc.exe': 1800, 'teams.exe': 1200})"
            }
        }
    },
    "retry": {
        "type": dict,
        "required": True,
        "fields": {
            "max_attempts": {"type": int, "required": True, "default": 5, "min": 1},
            "initial_backoff_seconds": {"type": int, "required": True, "default": 2, "min": 1},
            "max_backoff_seconds": {"type": int, "required": True, "default": 300, "min": 10}
        }
    },
    "dynamic_reload": {
        "type": dict,
        "required": True,
        "fields": {
            "enabled": {"type": bool, "required": True, "default": True},
            "check_interval": {"type": int, "required": True, "default": 30, "min": 5}
        }
    }
}

# Legacy field mappings for backward compatibility
LEGACY_FIELD_MAPPINGS = {
    "server_url": ("server", "url"),
    "api_key": ("authentication", "api_key"),  # Map to authentication section
    "api_token": ("authentication", "api_key"),  # Also map api_token to api_key
    "server_cert_fingerprint": ("server", "cert_pinning_fingerprint"),
    "allow_insecure_http": ("server", "allow_insecure_http"),
    "skip_cert_pinning": ("server", "allow_insecure_http"),  # Map to same field
    "skip_manifest_verification": ("server", "skip_manifest_verification"),
    "local_mode": ("_legacy", "local_mode"),  # Deprecated flag
    "intervals": {
        "aggregation_seconds": ("core", "aggregation_interval"),
        "upload_batch_seconds": ("core", "upload_interval"),
        "heartbeat_seconds": ("core", "heartbeat_interval"),
        "sample_seconds": ("helper", "heartbeat_interval"),
        "app_inventory_seconds": ("helper", "inventory_interval")
    },
    "features": {
        "capture_window_titles": ("helper", "features", "capture_window_titles"),
        "capture_full_urls": ("helper", "features", "capture_full_urls")
    },
    "thresholds": {
        "idle_seconds": ("thresholds", "idle_seconds")
    },
    "retry": {
        "max_attempts": ("retry", "max_attempts"),
        "initial_backoff_seconds": ("retry", "initial_backoff_seconds"),
        "max_backoff_seconds": ("retry", "max_backoff_seconds")
    }
}


class ConfigValidator:
    """Validates configuration against schema v2"""
    
    def __init__(self):
        self.schema = CONFIG_SCHEMA_V2
        self.errors = []
    
    def validate(self, config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any], list]:
        """
        Validate config against schema.
        Returns: (is_valid, normalized_config, errors)
        """
        self.errors = []
        normalized = {}
        
        # Validate each top-level field
        for field_name, field_schema in self.schema.items():
            value = config.get(field_name)
            
            # Check required fields
            if field_schema.get("required", False) and value is None:
                # Use default if available
                if "default" in field_schema:
                    value = field_schema["default"]
                else:
                    self.errors.append(f"Missing required field: {field_name}")
                    continue
            
            # Validate field
            if value is not None:
                normalized_value = self._validate_field(field_name, value, field_schema)
                if normalized_value is not None:
                    normalized[field_name] = normalized_value
        
        is_valid = len(self.errors) == 0
        return is_valid, normalized, self.errors
    
    def _validate_field(self, field_name: str, value: Any, schema: Dict) -> Optional[Any]:
        """Validate a single field against its schema"""
        expected_type = schema.get("type")
        
        # Type validation
        if not isinstance(value, expected_type):
            try:
                # Try to cast
                if expected_type == int:
                    value = int(value)
                elif expected_type == bool:
                    value = bool(value)
                elif expected_type == str:
                    value = str(value)
                else:
                    self.errors.append(f"Field '{field_name}' has wrong type. Expected {expected_type}, got {type(value)}")
                    return None
            except:
                self.errors.append(f"Field '{field_name}' cannot be converted to {expected_type}")
                return None
        
        # Range validation for integers
        if expected_type == int:
            min_val = schema.get("min")
            max_val = schema.get("max")
            
            if min_val is not None and value < min_val:
                self.errors.append(f"Field '{field_name}' value {value} is below minimum {min_val}")
                return None
            
            if max_val is not None and value > max_val:
                self.errors.append(f"Field '{field_name}' value {value} exceeds maximum {max_val}")
                return None
        
        # Nested dict validation
        if expected_type == dict and "fields" in schema:
            nested_result = {}
            for nested_name, nested_schema in schema["fields"].items():
                nested_value = value.get(nested_name)
                
                # Check required nested fields
                if nested_schema.get("required", False) and nested_value is None:
                    if "default" in nested_schema:
                        nested_value = nested_schema["default"]
                    else:
                        self.errors.append(f"Missing required nested field: {field_name}.{nested_name}")
                        continue
                
                # Validate nested field
                if nested_value is not None:
                    validated_nested = self._validate_field(
                        f"{field_name}.{nested_name}",
                        nested_value,
                        nested_schema
                    )
                    if validated_nested is not None:
                        nested_result[nested_name] = validated_nested
            
            return nested_result
        
        return value
    
    def get_default_config(self) -> Dict[str, Any]:
        """Generate a default configuration from schema"""
        return self._get_defaults_recursive(self.schema)

    def _get_defaults_recursive(self, schema_fields: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively generate defaults"""
        config = {}
        
        for field_name, field_schema in schema_fields.items():
            # Handle nested dicts
            if field_schema.get("type") == dict and "fields" in field_schema:
                config[field_name] = self._get_defaults_recursive(field_schema["fields"])
            
            # Handle simple fields with defaults
            elif "default" in field_schema:
                config[field_name] = field_schema["default"]
                
        return config


class ConfigMigrator:
    """Migrates legacy config formats to v2"""
    
    def __init__(self):
        self.validator = ConfigValidator()
    
    def migrate_v1_to_v2(self, old_config: Dict[str, Any]) -> Dict[str, Any]:
        """Migrate v1 config to v2 format"""
        logger.info("Migrating config from v1 to v2...")
        
        # Start with defaults
        new_config = self.validator.get_default_config()
        
        # Preserve agent identity
        if "agent_id" in old_config:
            new_config["agent"]["agent_id"] = old_config["agent_id"]
        
        if "local_agent_key" in old_config:
            new_config["agent"]["local_agent_key"] = old_config["local_agent_key"]
        
        # Migrate agent_name (custom display name)
        if "agent_name" in old_config:
            new_config["agent"]["agent_name"] = old_config["agent_name"]
        elif "hostname" in old_config:
            # Fallback to hostname if no agent_name
            new_config["agent"]["agent_name"] = old_config["hostname"]
        
        # Migrate server settings
        if "server_url" in old_config:
            new_config["server"]["url"] = old_config["server_url"]
        
        # SEC-002: Migrate registration_secret from root level
        if "registration_secret" in old_config:
            new_config["server"]["registration_secret"] = old_config["registration_secret"]
        
        if "server_cert_fingerprint" in old_config:
            new_config["server"]["cert_pinning_fingerprint"] = old_config["server_cert_fingerprint"]
        
        if "allow_insecure_http" in old_config:
            new_config["server"]["allow_insecure_http"] = old_config["allow_insecure_http"]
        
        if "skip_manifest_verification" in old_config:
            new_config["server"]["skip_manifest_verification"] = old_config["skip_manifest_verification"]
        
        # Migrate intervals
        intervals = old_config.get("intervals", {})
        if intervals:
            new_config["core"]["aggregation_interval"] = intervals.get("aggregation_seconds", 60)
            new_config["core"]["upload_interval"] = intervals.get("upload_batch_seconds", 60)
            new_config["core"]["heartbeat_interval"] = intervals.get("heartbeat_seconds", 60)
            new_config["helper"]["heartbeat_interval"] = intervals.get("sample_seconds", 10)
            new_config["helper"]["inventory_interval"] = intervals.get("app_inventory_seconds", 3600)
        
        # Migrate features
        features = old_config.get("features", {})
        if features:
            new_config["helper"]["features"]["capture_window_titles"] = features.get("capture_window_titles", False)
            new_config["helper"]["features"]["capture_full_urls"] = features.get("capture_full_urls", False)
            
            # Migrate optional flags if present
            if "enable_domains" in features:
                new_config["helper"]["features"]["enable_domains"] = features["enable_domains"]
            if "enable_inventory" in features:
                new_config["helper"]["features"]["enable_inventory"] = features["enable_inventory"]
            if "enable_app_tracking" in features:
                new_config["helper"]["features"]["enable_app_tracking"] = features["enable_app_tracking"]
            if "enable_idle_tracking" in features:
                new_config["helper"]["features"]["enable_idle_tracking"] = features["enable_idle_tracking"]
        
        # Migrate thresholds
        thresholds = old_config.get("thresholds", {})
        if thresholds:
            new_config["thresholds"]["idle_seconds"] = thresholds.get("idle_seconds", 120)
        
        # Migrate retry settings
        retry = old_config.get("retry", {})
        if retry:
            new_config["retry"]["max_attempts"] = retry.get("max_attempts", 5)
            new_config["retry"]["initial_backoff_seconds"] = retry.get("initial_backoff_seconds", 2)
            new_config["retry"]["max_backoff_seconds"] = retry.get("max_backoff_seconds", 300)
        
        # Migrate authentication data
        api_key = old_config.get("api_key") or old_config.get("api_token", "")
        if api_key:
            new_config["authentication"] = {
                "api_key": api_key,
                "api_key_stored_securely": False,
                "registered": True
            }
        
        # Keep legacy fields at root for backward compatibility
        new_config["api_key"] = api_key
        new_config["api_token"] = api_key
        
        logger.info("Migration complete")
        return new_config
    
    def is_v1_config(self, config: Dict[str, Any]) -> bool:
        """Check if config is v1 format"""
        version = config.get("version")
        if version is None or version == 1:
            return True
        return False
    
    def migrate_if_needed(self, config: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
        """
        Migrate config if needed.
        Returns: (migrated_config, was_migrated)
        """
        if self.is_v1_config(config):
            migrated = self.migrate_v1_to_v2(config)
            return migrated, True
        return config, False


def load_and_validate_config(config_path: Path) -> Tuple[Optional[Dict], list]:
    """
    Load, validate, and migrate config file.
    Returns: (validated_config, errors)
    """
    try:
        # Load config file
        if not config_path.exists():
            logger.warning(f"Config file not found: {config_path}")
            validator = ConfigValidator()
            return validator.get_default_config(), []
        
        with open(config_path, 'r') as f:
            raw_config = json.load(f)
        
        # Migrate if needed
        migrator = ConfigMigrator()
        config, was_migrated = migrator.migrate_if_needed(raw_config)
        
        if was_migrated:
            logger.info("Config was migrated from v1 to v2")
            # Save migrated config
            try:
                with open(config_path, 'w') as f:
                    json.dump(config, f, indent=2)
                logger.info(f"Saved migrated config to {config_path}")
            except Exception as e:
                logger.error(f"Failed to save migrated config: {e}")
        
        # Validate
        validator = ConfigValidator()
        is_valid, normalized_config, errors = validator.validate(config)
        
        if not is_valid:
            logger.error(f"Config validation failed: {errors}")
            return None, errors
        
        logger.info("Config validation successful")
        return normalized_config, []
        
    except json.JSONDecodeError as e:
        error_msg = f"Invalid JSON in config file: {e}"
        logger.error(error_msg)
        return None, [error_msg]
    except Exception as e:
        error_msg = f"Error loading config: {e}"
        logger.error(error_msg)
        return None, [error_msg]
