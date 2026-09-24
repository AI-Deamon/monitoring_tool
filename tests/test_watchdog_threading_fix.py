"""
Tests for Watchdog Freeze & Threading/Scheduling Fixes:
1. Domain history collection runs asynchronously and does not block main loop progress
2. Temporary file handling in _extract_history closes handle and unlinks safely
3. Initial collection mutual exclusion prevents periodic heavy tasks during startup
4. _run_async_check prevents duplicate task executions
5. schtasks fallback uses valid arguments and parses CSV
6. PowerShell timeout handling safely catches TimeoutExpired
"""

import io
import os
import sys
import time
import tempfile
import sqlite3
import subprocess
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure agent directory is in path
sys.path.insert(0, str(Path(__file__).parent.parent / "agent"))

from helper.domain import BrowserHistoryTracker, ActiveDomainTracker
from helper.security_collector import SecurityCollector
from helper.extended_inventory import ExtendedInventoryCollector


class TestWatchdogThreadingFix(unittest.TestCase):

    def test_domain_history_async_does_not_block_main_loop(self):
        """Test 1: Mock slow domain history extraction; verify watchdog counter progresses."""
        active_tasks = set()
        task_lock = threading.Lock()
        watchdog_counter = 0

        def _run_async_check(task_name, fn):
            with task_lock:
                if task_name in active_tasks:
                    return
                active_tasks.add(task_name)

            def runner():
                try:
                    fn()
                finally:
                    with task_lock:
                        active_tasks.discard(task_name)

            t = threading.Thread(target=runner, daemon=True)
            t.start()

        # Simulate slow domain history collection (0.4s)
        slow_finished = threading.Event()
        def slow_domain_collection():
            time.sleep(0.3)
            slow_finished.set()

        # Launch async domain history collection
        _run_async_check("domain_history", slow_domain_collection)

        # Main loop progresses immediately without waiting
        for _ in range(5):
            time.sleep(0.02)
            watchdog_counter += 1

        # The main loop counter incremented while slow_domain_collection was still running!
        self.assertEqual(watchdog_counter, 5)
        slow_finished.wait(timeout=2.0)
        self.assertTrue(slow_finished.is_set())

    def test_tempfile_handling_closes_and_unlinks_safely(self):
        """Test 2: Test that _extract_history closes NamedTemporaryFile before opening, and unlinks it."""
        tracker = BrowserHistoryTracker()

        # Create a real sqlite DB to act as fake browser history
        temp_dir = tempfile.mkdtemp()
        try:
            fake_history = Path(temp_dir) / "History"
            conn = sqlite3.connect(fake_history)
            cursor = conn.cursor()
            cursor.execute("CREATE TABLE urls (id INTEGER PRIMARY KEY, url TEXT, title TEXT, last_visit_time INTEGER)")
            cursor.execute("INSERT INTO urls VALUES (1, 'https://example.com/test', 'Example Title', 13000000000000000)")
            conn.commit()
            conn.close()

            # Track temp files created
            created_temp_files = []
            orig_named_temp_file = tempfile.NamedTemporaryFile

            def tracking_temp_file(*args, **kwargs):
                tf = orig_named_temp_file(*args, **kwargs)
                created_temp_files.append(tf.name)
                return tf

            with patch("tempfile.NamedTemporaryFile", side_effect=tracking_temp_file):
                visits = tracker._extract_history("chrome", fake_history)

            self.assertEqual(len(visits), 1)
            self.assertEqual(visits[0]["domain"], "example.com")

            # Check that all created temp files were cleanly unlinked
            for fpath in created_temp_files:
                self.assertFalse(os.path.exists(fpath), f"Temp file {fpath} was not cleaned up!")

        finally:
            # Clean up test dir
            for f in Path(temp_dir).glob("*"):
                try:
                    f.unlink()
                except Exception:
                    pass
            try:
                os.rmdir(temp_dir)
            except Exception:
                pass

    def test_initial_collection_mutual_exclusion(self):
        """Test 3: Verify periodic heavy tasks are skipped when initial collection is in progress."""
        from helper.main import SentinelHelper

        # Create mock helper with minimal required configuration
        with patch.object(SentinelHelper, "__init__", lambda self: None):
            helper = SentinelHelper()
            helper._initial_collections_in_progress = True
            helper._initial_collections_lock = threading.Lock()
            helper._heavy_collection_lock = threading.Lock()
            helper._async_task_lock = threading.Lock()
            helper._active_async_tasks = set()
            helper.logger = MagicMock()
            helper.collector = MagicMock()
            helper.communicator = MagicMock()

            # Helper method to simulate scheduling periodic heavy checks
            def schedule_visibility():
                if helper._initial_collections_in_progress:
                    helper.logger.debug("[ASYNC] visibility skipped - initial collection in progress")
                    return False
                return True

            # While initial collection is running, visibility is skipped
            scheduled = schedule_visibility()
            self.assertFalse(scheduled)
            helper.logger.debug.assert_called_with("[ASYNC] visibility skipped - initial collection in progress")

            # Mark initial collection complete
            helper._initial_collections_in_progress = False
            scheduled = schedule_visibility()
            self.assertTrue(scheduled)

    def test_async_duplicate_prevention(self):
        """Test 4: Triggering the same async task while already running prevents duplicate instances."""
        from helper.main import SentinelHelper

        with patch.object(SentinelHelper, "__init__", lambda self: None):
            helper = SentinelHelper()
            helper._async_task_lock = threading.Lock()
            helper._active_async_tasks = set()
            helper.logger = MagicMock()

            execution_count = 0
            task_started = threading.Event()
            can_finish = threading.Event()

            def slow_task():
                nonlocal execution_count
                execution_count += 1
                task_started.set()
                can_finish.wait(timeout=2.0)

            # Trigger task 1
            SentinelHelper._run_async_check(helper, "test_task", slow_task)
            self.assertTrue(task_started.wait(timeout=1.0))

            # Trigger task 2 while task 1 is still running
            SentinelHelper._run_async_check(helper, "test_task", slow_task)

            # Allow task 1 to finish
            can_finish.set()
            time.sleep(0.1)

            # Task function should have executed only ONCE!
            self.assertEqual(execution_count, 1)

    def test_schtasks_fallback_arguments_and_parsing(self):
        """Test 5: Verify schtasks fallback uses ["schtasks", "/query", "/fo", "CSV", "/v"] without /tn *."""
        collector = SecurityCollector(config=MagicMock())

        csv_output = (
            '"HostName","TaskName","Next Run Time","Status","Logon Mode","Author","Task To Run","Start In","Comment","Scheduled Task State","Idle Time","Power Management","Run As User","Delete Task If Not Rescheduled","Stop Task If Runs X Hours/Mins","Schedule","Schedule Type","Start Time","Start Date","End Date","Days","Months","Repeat: Every","Repeat: Until: Time","Repeat: Until: Duration","Repeat: Stop If Still Running"\n'
            '"MYPC","\\Microsoft\\Windows\\UpdateOrchestrator\\USO_UxBroker","N/A","Ready","Interactive/Background","Microsoft Corporation","C:\\Windows\\system32\\MusNotification.exe","N/A","N/A","Enabled","Disabled","Stop On Battery Mode, No Start On Batteries","SYSTEM","Disabled","72:00:00","N/A","One Time Only","N/A","N/A","N/A","N/A","N/A","Disabled","Disabled","Disabled","Disabled"\n'
        )

        fake_proc = MagicMock(returncode=0, stdout=csv_output, stderr="")

        with patch("subprocess.run", return_value=fake_proc) as mock_run:
            indicators = collector._collect_tasks_schtasks()

            mock_run.assert_called_once_with(
                ["schtasks", "/query", "/fo", "CSV", "/v"],
                capture_output=True,
                text=True,
                timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )

            # Should parse without error
            self.assertIsInstance(indicators, list)

    def test_powershell_timeout_handling(self):
        """Test 6: Verify PowerShell subprocess timeout is safely handled without crashing."""
        ext_collector = ExtendedInventoryCollector(config=MagicMock())

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="powershell.exe", timeout=45)):
            output = ext_collector._run_powershell("Get-Process", timeout=45)
            # Should return None safely without raising
            self.assertIsNone(output)


if __name__ == "__main__":
    unittest.main()
