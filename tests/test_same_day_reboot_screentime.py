import unittest
import tempfile
import shutil
import time
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

import sys
AGENT_DIR = Path(__file__).parent.parent / "agent"
SERVER_DIR = Path(__file__).parent.parent / "server"
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(SERVER_DIR))

# Ensure server .env is loaded
from dotenv import load_dotenv
load_dotenv(SERVER_DIR / ".env", override=True)

from agent.core.state_machine import ScreenTimeEngine, ScreenState, LastEvent, _now_ist
from agent.helper.collector import DataCollector, _local_date
from agent.helper.config import HelperConfig


class TestSameDayRebootScreenTime(unittest.TestCase):
    """
    Test suite verifying screen time preservation across same-day shutdowns & reboots.
    Scenario:
      10:00–11:00 AM: 1 hour active work (3600s)
      11:00–12:00 PM: Laptop shutdown (offline 1 hr)
      12:00–01:00 PM: Laptop rebooted, 1 hour active work (3600s)
      Expected total: 7200s (2.0 hours), 0 seconds lost.
    """

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.state_file = self.test_dir / "screentime_state.json"
        self.helper_state_file = self.test_dir / "helper_state.json"

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_agent_reboot_preserves_cumulative_counters(self):
        """
        Verify that shutting down at 11:00 and rebooting at 12:00 preserves
        the 3600s from the morning, reaching 7200s after the afternoon session.
        """
        # --- Morning Session (10:00 - 11:00) ---
        engine1 = ScreenTimeEngine(data_dir=self.test_dir, agent_id="test-agent")
        engine1.current_state = ScreenState.ACTIVE
        engine1.active_seconds = 3600.0  # Accumulated during 10:00-11:00
        engine1.last_timestamp = time.time() - 10.0  # 10s active tick
        
        # Shut down at 11:00 AM
        engine1.mark_shutdown()
        self.assertEqual(engine1.last_event, LastEvent.SHUTDOWN)
        self.assertAlmostEqual(engine1.active_seconds, 3610.0, delta=2.0)

        # Verify state file was written
        self.assertTrue(self.state_file.exists())
        with open(self.state_file, "r") as f:
            saved = json.load(f)
            self.assertAlmostEqual(saved["active_seconds"], 3610.0, delta=2.0)
            self.assertEqual(saved["last_event"], "shutdown")

        # --- Afternoon Session (12:00 - 13:00) after reboot ---
        engine2 = ScreenTimeEngine(data_dir=self.test_dir, agent_id="test-agent")
        persisted = engine2.load_persisted_state()
        self.assertIsNotNone(persisted)
        self.assertAlmostEqual(engine2.active_seconds, 3610.0, delta=2.0)

        # Startup gap handling (shutdown gap is ignored)
        gap_info = engine2.handle_startup(persisted)
        self.assertEqual(gap_info["action"], "ignored_shutdown_gap")
        self.assertAlmostEqual(engine2.active_seconds, 3610.0, delta=2.0)

        # Simulate 1 hour of afternoon work (120 ticks of 30s)
        for _ in range(120):
            engine2.last_timestamp = time.time() - 30.0
            engine2.tick()

        # Cumulative active seconds must equal 3610 + 3600 = 7210s (~2.0 hours)
        self.assertAlmostEqual(engine2.active_seconds, 7210.0, delta=10.0)

    def test_collector_session_start_persistence_same_day(self):
        """
        Verify that DataCollector persists daily_session_start across reboots on the same day.
        """
        config = HelperConfig()
        config.data_dir = self.test_dir
        config.state_dir = self.test_dir
        config.state_file = self.helper_state_file

        collector1 = DataCollector(config)
        morning_session_start = collector1._session_start.isoformat()
        self.assertTrue(self.helper_state_file.exists())

        # Verify state file contains daily_session_start and daily_session_date
        with open(self.helper_state_file, "r") as f:
            data = json.load(f)
            self.assertEqual(data["daily_session_start"], morning_session_start)
            self.assertEqual(data["daily_session_date"], str(_local_date()))

        # Simulate reboot: create new collector instance
        collector2 = DataCollector(config)
        # Should have restored morning session start!
        self.assertEqual(collector2._session_start.isoformat(), morning_session_start)

    def test_postgres_greatest_reboot_protection(self):
        """
        Verify process_screentime_event stored procedure logic using SQLAlchemy against PostgreSQL.
        """
        try:
            from server_app import create_app, db
            from sqlalchemy import text
        except ImportError as e:
            self.skipTest(f"Server app import failed: {e}")

        app = create_app()
        with app.app_context():
            # Get an existing valid agent_id
            row = db.session.execute(text("SELECT agent_id FROM agents LIMIT 1")).fetchone()
            if not row:
                self.skipTest("No agent registered in DB to test stored procedure")
            agent_id = str(row[0])

            test_date = datetime(2099, 1, 1, 10, 0, 0)
            
            # Ensure clean state for test date
            db.session.execute(text("DELETE FROM screen_time WHERE agent_id = :aid AND date = :d"), {
                'aid': agent_id, 'd': test_date.date()
            })
            db.session.commit()

            try:
                # 1. First session (10:00–11:00): 3600s active
                res1 = db.session.execute(text("""
                    SELECT * FROM process_screentime_event(
                        :agent_id, :ts, :active, :idle, :locked, :away, :state, :session_start
                    )
                """), {
                    'agent_id': agent_id,
                    'ts': test_date,
                    'active': 3600,
                    'idle': 0,
                    'locked': 0,
                    'away': 0,
                    'state': 'active',
                    'session_start': test_date - timedelta(hours=1)
                }).fetchone()
                db.session.commit()
                self.assertEqual(res1[0], 'success', f"Procedure returned error: {res1[1]}")

                # Verify DB stores 3600
                res = db.session.execute(text(
                    "SELECT active_seconds FROM screen_time WHERE agent_id = :aid AND date = :d"
                ), {'aid': agent_id, 'd': test_date.date()}).fetchone()
                self.assertIsNotNone(res)
                self.assertEqual(res[0], 3600)

                # 2. Reboot happens at 12:00: first payload sends 15s with a new session_start
                reboot_time = datetime(2099, 1, 1, 12, 0, 15)
                res2_proc = db.session.execute(text("""
                    SELECT * FROM process_screentime_event(
                        :agent_id, :ts, :active, :idle, :locked, :away, :state, :session_start
                    )
                """), {
                    'agent_id': agent_id,
                    'ts': reboot_time,
                    'active': 15,
                    'idle': 0,
                    'locked': 0,
                    'away': 0,
                    'state': 'active',
                    'session_start': reboot_time
                }).fetchone()
                db.session.commit()
                self.assertEqual(res2_proc[0], 'success', f"Procedure returned error: {res2_proc[1]}")

                # CRITICAL: Active seconds MUST NOT drop to 15! It must remain 3600!
                res2 = db.session.execute(text(
                    "SELECT active_seconds FROM screen_time WHERE agent_id = :aid AND date = :d"
                ), {'aid': agent_id, 'd': test_date.date()}).fetchone()
                self.assertEqual(res2[0], 3600, "GREATEST logic failed! Active time was reduced upon reboot.")

                # 3. Afternoon session accumulates to 7200s (2.0 hours)
                afternoon_end = datetime(2099, 1, 1, 13, 0, 0)
                res3_proc = db.session.execute(text("""
                    SELECT * FROM process_screentime_event(
                        :agent_id, :ts, :active, :idle, :locked, :away, :state, :session_start
                    )
                """), {
                    'agent_id': agent_id,
                    'ts': afternoon_end,
                    'active': 7200,
                    'idle': 0,
                    'locked': 0,
                    'away': 0,
                    'state': 'active',
                    'session_start': test_date - timedelta(hours=1)
                }).fetchone()
                db.session.commit()
                self.assertEqual(res3_proc[0], 'success', f"Procedure returned error: {res3_proc[1]}")

                res3 = db.session.execute(text(
                    "SELECT active_seconds FROM screen_time WHERE agent_id = :aid AND date = :d"
                ), {'aid': agent_id, 'd': test_date.date()}).fetchone()
                self.assertEqual(res3[0], 7200)

            finally:
                # Cleanup test row
                db.session.execute(text("DELETE FROM screen_time WHERE agent_id = :aid AND date = :d"), {
                    'aid': agent_id, 'd': test_date.date()
                })
                db.session.commit()


if __name__ == "__main__":
    unittest.main()
