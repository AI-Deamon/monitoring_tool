"""Module-level loggers must actually reach the log file.

setup_logger() attached its handlers to a NAMED logger ("SentinelCore"), and
every module outside service.py uses logging.getLogger(__name__) - core.updater,
core.buffer, helper.state_detector and so on. Those are siblings of
"SentinelCore", not descendants, so their records propagated to a root logger
with no handlers and hit logging.lastResort: INFO dropped entirely,
WARNING/ERROR emitted to stderr raw with no timestamp, level or source.

Measured on L180701PB 2026-07-29: core.log held 809 records, ALL of them from
service.py, and zero from updater.py. That is why the update subsystem's whole
success path was invisible - complete_update() logged "[OK] Self-test passed"
at INFO and it went nowhere - and it is a large part of why the 60s swap stall
survived three releases unnoticed.
"""

import logging
import os
import sys
import tempfile
import unittest
from logging.handlers import RotatingFileHandler
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agent'))

from logger import setup_logger


class LoggingRoutingTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.log_file = Path(self._tmp.name) / 'core.log'

        root = logging.getLogger()
        self._saved_handlers = root.handlers[:]
        self._saved_level = root.level
        root.handlers = []

    def tearDown(self):
        root = logging.getLogger()
        for handler in root.handlers[:]:
            handler.close()
            root.removeHandler(handler)
        root.handlers = self._saved_handlers
        root.setLevel(self._saved_level)

        for name in ('SentinelCore', 'core.updater', 'helper.state_detector'):
            stray = logging.getLogger(name)
            stray.handlers = []
            stray.propagate = True

        self._tmp.cleanup()

    def _read_log(self):
        for handler in logging.getLogger().handlers:
            handler.flush()
        if not self.log_file.exists():
            return ''
        return self.log_file.read_text(encoding='utf-8', errors='replace')


class TestModuleLoggersReachTheFile(LoggingRoutingTestBase):
    def test_module_logger_info_reaches_the_log_file(self):
        setup_logger('SentinelCore', str(self.log_file), logging.INFO)

        logging.getLogger('core.updater').info('[UPDATER] [OK] Self-test passed')

        self.assertIn('Self-test passed', self._read_log())

    def test_module_logger_records_carry_their_source(self):
        setup_logger('SentinelCore', str(self.log_file), logging.INFO)

        logging.getLogger('core.updater').warning('[UPDATER] signature mismatch')

        contents = self._read_log()
        self.assertIn('core.updater', contents)
        self.assertIn('WARNING', contents)

    def test_named_service_logger_still_writes(self):
        logger = setup_logger('SentinelCore', str(self.log_file), logging.INFO)

        logger.info('Service is running')

        self.assertIn('Service is running', self._read_log())

    def test_service_logger_records_are_not_duplicated(self):
        # Handlers on BOTH the named logger and root would log every
        # service.py line twice.
        logger = setup_logger('SentinelCore', str(self.log_file), logging.INFO)

        logger.info('UNIQUE-MARKER-XYZ')

        self.assertEqual(self._read_log().count('UNIQUE-MARKER-XYZ'), 1)

    def test_repeated_setup_does_not_stack_handlers(self):
        setup_logger('SentinelCore', str(self.log_file), logging.INFO)
        setup_logger('SentinelCore', str(self.log_file), logging.INFO)

        logging.getLogger('core.updater').info('ONCE-ONLY')

        self.assertEqual(self._read_log().count('ONCE-ONLY'), 1)
        file_handlers = [
            h for h in logging.getLogger().handlers
            if isinstance(h, RotatingFileHandler)
        ]
        self.assertEqual(len(file_handlers), 1)

    def test_noisy_third_party_loggers_are_capped_at_warning(self):
        # Routing to root means urllib3's per-request chatter would otherwise
        # land in core.log at INFO on every upload.
        setup_logger('SentinelCore', str(self.log_file), logging.INFO)

        logging.getLogger('urllib3.connectionpool').info('GET /api/v1 200')

        self.assertNotIn('GET /api/v1 200', self._read_log())


if __name__ == '__main__':
    unittest.main()
