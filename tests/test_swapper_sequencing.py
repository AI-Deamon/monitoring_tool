"""Swapper stop sequencing.

The swapper's first act used to be waiting for the core process to exit, with
a 60s timeout. The core has no code path that exits on its own - its update
worker only returns from a thread - so that timeout expired on every recorded
swap (3.7.0->4.0.0, 4.0.0->4.0.2, 4.1.0->4.2.0) and the swapper force-stopped
the service anyway.

Stopping the service IS how the core exits. These tests pin that contract.
"""

import os
import sys
import unittest
import unittest.mock
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agent'))

from tools import swapper


class TestStopService(unittest.TestCase):
    def test_returns_true_once_scm_reports_stopped(self):
        states = ['RUNNING', 'STOP_PENDING', 'STOPPED']

        with patch.object(swapper, '_run_command', return_value=(True, '', '')), \
             patch.object(swapper, '_get_service_state', side_effect=states), \
             patch.object(swapper.time, 'sleep'):
            ok = swapper._stop_service(Path('C:/nope'), 'WinDiagSvc', timeout=30)

        self.assertTrue(ok)

    def test_returns_false_when_service_never_stops(self):
        with patch.object(swapper, '_run_command', return_value=(True, '', '')), \
             patch.object(swapper, '_get_service_state', return_value='RUNNING'), \
             patch.object(swapper.time, 'sleep'):
            ok = swapper._stop_service(Path('C:/nope'), 'WinDiagSvc', timeout=4)

        self.assertFalse(ok)

    def test_already_stopped_service_issues_no_stop_command(self):
        with patch.object(swapper, '_run_command') as run, \
             patch.object(swapper, '_get_service_state', return_value='STOPPED'), \
             patch.object(swapper.time, 'sleep'):
            ok = swapper._stop_service(Path('C:/nope'), 'WinDiagSvc', timeout=30)

        self.assertTrue(ok)
        run.assert_not_called()

    def test_parent_pid_wait_is_gone(self):
        # The 60s wait can never succeed - it must not exist any more.
        self.assertFalse(hasattr(swapper, '_wait_for_process_exit'))
        self.assertFalse(hasattr(swapper, 'PARENT_EXIT_TIMEOUT_SECONDS'))


if __name__ == '__main__':
    unittest.main()
