"""
Tests for auto-update interval fix (6h -> 30min)
and version reporting on every poll.

Fix 1: Default update_check_interval should be 1800 seconds (30 min), not 21600 (6h).
Fix 3: Server should update agents.version on every /latest poll using X-Agent-Version header.
"""
import json
import tempfile
import uuid
from pathlib import Path
import pytest


class TestUpdateIntervalDefault:
    """Fix 1: Default update check interval should be 30 minutes (1800s), not 6 hours (21600s)."""

    def test_default_interval_is_30_minutes(self):
        """Default update_check_interval should be 1800 seconds (30 min)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            # Minimal valid config matching schema - no updates.check_interval set
            config_data = {
                "agent": {
                    "agent_id": "test-agent-001",
                    "local_agent_key": "test-key-123",
                },
                "server": {
                    "url": "http://localhost:5050",
                },
                "core": {
                    "listen_port": 48123,
                    "aggregation_interval": 60,
                    "upload_interval": 60,
                    "heartbeat_interval": 60,
                    "enable_ingest": True,
                    "enable_uploader": True,
                    "enable_aggregator": True,
                },
                "helper": {
                    "heartbeat_interval": 10,
                    "domain_interval": 60,
                    "inventory_interval": 3600,
                    "features": {
                        "capture_window_titles": True,
                        "capture_full_urls": False,
                        "enable_domains": True,
                        "enable_idle_detection": True,
                        "enable_app_tracking": True,
                    },
                },
                "performance": {
                    "max_cpu_percent": 5,
                    "max_memory_mb": 256,
                    "batch_size": 50,
                },
                "dynamic_reload": {
                    "enabled": True,
                    "check_interval": 30,
                },
                # NO updates.check_interval — should use default of 1800
            }
            config_path.write_text(json.dumps(config_data))

            import sys
            agent_root = Path(__file__).parent.parent / "agent"
            sys.path.insert(0, str(agent_root))
            from core.config import CoreConfig

            config = CoreConfig(config_path=str(config_path))

            assert config.update_check_interval == 1800, (
                f"Expected default 1800s (30 min), got {config.update_check_interval}s"
            )

    def test_config_json_can_override_interval(self):
        """config.json updates.check_interval should override default."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            config_data = {
                "agent": {
                    "agent_id": "test-agent-001",
                    "local_agent_key": "test-key-123",
                },
                "server": {
                    "url": "http://localhost:5050",
                },
                "core": {
                    "listen_port": 48123,
                    "aggregation_interval": 60,
                    "upload_interval": 60,
                    "heartbeat_interval": 60,
                    "enable_ingest": True,
                    "enable_uploader": True,
                    "enable_aggregator": True,
                },
                "helper": {
                    "heartbeat_interval": 10,
                    "domain_interval": 60,
                    "inventory_interval": 3600,
                    "features": {
                        "capture_window_titles": True,
                        "capture_full_urls": False,
                        "enable_domains": True,
                        "enable_idle_detection": True,
                        "enable_app_tracking": True,
                    },
                },
                "performance": {
                    "max_cpu_percent": 5,
                    "max_memory_mb": 256,
                    "batch_size": 50,
                },
                "dynamic_reload": {
                    "enabled": True,
                    "check_interval": 30,
                },
                "updates": {
                    "check_interval": 600,  # 10 minutes — explicit override
                },
            }
            config_path.write_text(json.dumps(config_data))

            import sys
            agent_root = Path(__file__).parent.parent / "agent"
            sys.path.insert(0, str(agent_root))
            from core.config import CoreConfig

            config = CoreConfig(config_path=str(config_path))
            assert config.update_check_interval == 600

    def test_old_6h_config_still_works(self):
        """Agents with explicit 6h config should keep it (backward compat)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            config_data = {
                "agent": {
                    "agent_id": "test-agent-001",
                    "local_agent_key": "test-key-123",
                },
                "server": {
                    "url": "http://localhost:5050",
                },
                "core": {
                    "listen_port": 48123,
                    "aggregation_interval": 60,
                    "upload_interval": 60,
                    "heartbeat_interval": 60,
                    "enable_ingest": True,
                    "enable_uploader": True,
                    "enable_aggregator": True,
                },
                "helper": {
                    "heartbeat_interval": 10,
                    "domain_interval": 60,
                    "inventory_interval": 3600,
                    "features": {
                        "capture_window_titles": True,
                        "capture_full_urls": False,
                        "enable_domains": True,
                        "enable_idle_detection": True,
                        "enable_app_tracking": True,
                    },
                },
                "performance": {
                    "max_cpu_percent": 5,
                    "max_memory_mb": 256,
                    "batch_size": 50,
                },
                "dynamic_reload": {
                    "enabled": True,
                    "check_interval": 30,
                },
                "updates": {
                    "check_interval": 21600,  # Old 6-hour setting
                },
            }
            config_path.write_text(json.dumps(config_data))

            import sys
            agent_root = Path(__file__).parent.parent / "agent"
            sys.path.insert(0, str(agent_root))
            from core.config import CoreConfig

            config = CoreConfig(config_path=str(config_path))
            assert config.update_check_interval == 21600


class TestVersionReportingOnPoll:
    """Fix 3: Server should update agents.version on every /latest poll."""

    @pytest.fixture(autouse=True)
    def _isolate_env(self, monkeypatch):
        """Point this class at in-memory SQLite without leaking the change.

        Assigning to os.environ directly outlives the test, and other suites
        (e.g. test_midnight_span_handling) deliberately run against the real
        DATABASE_URL - they then fail with "no such table: agents".
        """
        monkeypatch.setenv('FLASK_ENV', 'development')
        monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')
        monkeypatch.setenv('SECRET_KEY', 'test-secret-key-for-unit-tests')

    def _create_test_app(self):
        """Create a Flask app configured for SQLite testing."""
        import sys
        server_root = Path(__file__).parent.parent / "server"
        sys.path.insert(0, str(server_root))

        from server_app import create_app
        from extensions import db
        import server_models

        app = create_app()
        app.config['TESTING'] = True
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        return app, db, server_models

    def test_version_updated_on_poll(self):
        """When agent polls /latest, server should update agents.version."""
        app, db, server_models = self._create_test_app()

        with app.app_context():
            db.create_all()

            test_agent_id = uuid.uuid4()
            agent = server_models.Agent(
                agent_id=test_agent_id,
                hostname="TEST-PC",
                version="2.3.0",
                update_status="up_to_date",
            )
            db.session.add(agent)
            db.session.commit()
            assert agent.version == "2.3.0"

            with app.test_client() as client:
                response = client.get(
                    '/api/v1/updates/latest',
                    headers={
                        'X-Agent-ID': str(test_agent_id),
                        'X-Agent-Version': '2.4.0',
                    }
                )

            db.session.refresh(agent)
            assert agent.version == "2.4.0", (
                f"Expected agent.version='2.4.0', got '{agent.version}'"
            )

            data = response.get_json()
            assert data.get('update_available') is False

            db.session.remove()

    def test_version_not_updated_when_unknown(self):
        """Server should not update version when X-Agent-Version is 'unknown'."""
        app, db, server_models = self._create_test_app()

        with app.app_context():
            db.create_all()

            test_agent_id = uuid.uuid4()
            agent = server_models.Agent(
                agent_id=test_agent_id,
                hostname="TEST-PC-2",
                version="2.3.0",
                update_status="up_to_date",
            )
            db.session.add(agent)
            db.session.commit()

            with app.test_client() as client:
                response = client.get(
                    '/api/v1/updates/latest',
                    headers={
                        'X-Agent-ID': str(test_agent_id),
                        'X-Agent-Version': 'unknown',
                    }
                )

            db.session.refresh(agent)
            assert agent.version == "2.3.0", (
                f"Expected agent.version to remain '2.3.0', got '{agent.version}'"
            )

            db.session.remove()
