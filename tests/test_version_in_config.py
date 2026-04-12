"""
Tests for version control in config.json.

Verifies that:
1. Schema accepts current_version and last_update_time in agent section
2. Agent reads current_version from config.json as fallback when version.json missing
3. Agent writes version to config.json after successful update
"""
import json
import tempfile
import uuid
from pathlib import Path
import pytest
import os


class TestConfigSchemaVersionFields:
    """Schema should accept current_version and last_update_time in agent section."""

    def test_schema_accepts_current_version(self):
        """Config schema should accept agent.current_version field."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            config_data = {
                "version": 2,
                "agent": {
                    "agent_id": "test-agent-001",
                    "local_agent_key": "test-key",
                    "current_version": "2.4.0",
                },
                "server": {"url": "http://localhost:5050"},
                "core": {
                    "listen_port": 48123, "aggregation_interval": 60,
                    "upload_interval": 60, "heartbeat_interval": 60,
                    "enable_ingest": True, "enable_uploader": True, "enable_aggregator": True,
                },
                "helper": {
                    "heartbeat_interval": 10, "domain_interval": 60, "inventory_interval": 3600,
                    "features": {
                        "capture_window_titles": True, "capture_full_urls": False,
                        "enable_domains": True, "enable_idle_detection": True, "enable_app_tracking": True,
                    },
                },
                "performance": {"max_cpu_percent": 5, "max_memory_mb": 256, "batch_size": 50},
                "dynamic_reload": {"enabled": True, "check_interval": 30},
            }
            config_path.write_text(json.dumps(config_data))

            import sys
            sys.path.insert(0, str(Path(__file__).parent.parent / "agent"))
            from core.config import CoreConfig

            config = CoreConfig(config_path=str(config_path))

            assert hasattr(config, 'current_version'), (
                "CoreConfig should have current_version attribute"
            )
            assert config.current_version == "2.4.0"

    def test_schema_accepts_last_update_time(self):
        """Config schema should accept agent.last_update_time field."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            config_data = {
                "version": 2,
                "agent": {
                    "agent_id": "test-agent-001",
                    "local_agent_key": "test-key",
                    "last_update_time": "2026-04-10T12:00:00+00:00",
                },
                "server": {"url": "http://localhost:5050"},
                "core": {
                    "listen_port": 48123, "aggregation_interval": 60,
                    "upload_interval": 60, "heartbeat_interval": 60,
                    "enable_ingest": True, "enable_uploader": True, "enable_aggregator": True,
                },
                "helper": {
                    "heartbeat_interval": 10, "domain_interval": 60, "inventory_interval": 3600,
                    "features": {
                        "capture_window_titles": True, "capture_full_urls": False,
                        "enable_domains": True, "enable_idle_detection": True, "enable_app_tracking": True,
                    },
                },
                "performance": {"max_cpu_percent": 5, "max_memory_mb": 256, "batch_size": 50},
                "dynamic_reload": {"enabled": True, "check_interval": 30},
            }
            config_path.write_text(json.dumps(config_data))

            import sys
            sys.path.insert(0, str(Path(__file__).parent.parent / "agent"))
            from core.config import CoreConfig

            config = CoreConfig(config_path=str(config_path))

            assert hasattr(config, 'last_update_time'), (
                "CoreConfig should have last_update_time attribute"
            )


class TestVersionFallback:
    """Agent should read current_version from config.json when version.json is missing."""

    def test_fallback_to_config_when_version_json_missing(self):
        """If version.json doesn't exist, AgentUpdater should use config.current_version."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent"))

        from core.updater import AgentUpdater
        from core.config import CoreConfig

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            config_data = {
                "version": 2,
                "agent": {
                    "agent_id": "test-agent-001",
                    "local_agent_key": "test-key",
                    "current_version": "2.5.0",
                },
                "server": {"url": "http://localhost:5050"},
                "core": {
                    "listen_port": 48123, "aggregation_interval": 60,
                    "upload_interval": 60, "heartbeat_interval": 60,
                    "enable_ingest": True, "enable_uploader": True, "enable_aggregator": True,
                },
                "helper": {
                    "heartbeat_interval": 10, "domain_interval": 60, "inventory_interval": 3600,
                    "features": {
                        "capture_window_titles": True, "capture_full_urls": False,
                        "enable_domains": True, "enable_idle_detection": True, "enable_app_tracking": True,
                    },
                },
                "performance": {"max_cpu_percent": 5, "max_memory_mb": 256, "batch_size": 50},
                "dynamic_reload": {"enabled": True, "check_interval": 30},
            }
            config_path.write_text(json.dumps(config_data))

            config = CoreConfig(config_path=str(config_path))
            updater = AgentUpdater(config)

            assert updater.current_version == "2.5.0", (
                f"Expected '2.5.0' from config.json fallback, got '{updater.current_version}'"
            )


class TestVersionWriteBack:
    """After successful update, agent should write version to config.json."""

    def test_save_config_writes_version_fields(self):
        """save_config() should write current_version and last_update_time to config.json."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "agent"))

        from core.config import CoreConfig
        from datetime import datetime, timezone

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            config_data = {
                "version": 2,
                "agent": {
                    "agent_id": "test-agent-001",
                    "local_agent_key": "test-key",
                    "current_version": "2.3.0",
                },
                "server": {"url": "http://localhost:5050"},
                "core": {
                    "listen_port": 48123, "aggregation_interval": 60,
                    "upload_interval": 60, "heartbeat_interval": 60,
                    "enable_ingest": True, "enable_uploader": True, "enable_aggregator": True,
                },
                "helper": {
                    "heartbeat_interval": 10, "domain_interval": 60, "inventory_interval": 3600,
                    "features": {
                        "capture_window_titles": True, "capture_full_urls": False,
                        "enable_domains": True, "enable_idle_detection": True, "enable_app_tracking": True,
                    },
                },
                "performance": {"max_cpu_percent": 5, "max_memory_mb": 256, "batch_size": 50},
                "dynamic_reload": {"enabled": True, "check_interval": 30},
            }
            config_path.write_text(json.dumps(config_data))

            config = CoreConfig(config_path=str(config_path))

            # Simulate post-update state
            config.current_version = "2.5.0"
            config.last_update_time = datetime.now(timezone.utc).isoformat()
            config.save_config()

            # Read back config.json
            saved = json.loads(config_path.read_text())
            assert saved["agent"]["current_version"] == "2.5.0", (
                f"Expected config.json agent.current_version='2.5.0', "
                f"got '{saved['agent'].get('current_version')}'"
            )
            assert "last_update_time" in saved["agent"]
            assert saved["agent"]["last_update_time"] != ""
