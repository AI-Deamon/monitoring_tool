"""The swapper must be able to update itself.

A running EXE cannot replace itself on Windows, so swapper.py only ever
replaced windiag.exe, syshealth.exe and version.json - never
tools/swapper.exe. Proven in the field: the 4.1.0 -> 4.2.0 update on
2026-07-28 shipped a swapper.exe inside its package and left the installed
one untouched (still dated 2026-07-14). Every swapper fix therefore needed a
manual, elevated install on every machine.

The fix has two halves:
  1. the core extracts the new swapper from the VERIFIED package and runs
     that copy, so the new logic applies to the update that ships it;
  2. that copy installs itself into the canonical path only AFTER it has
     driven a complete, successful swap - a broken swapper never replaces
     the known-good one.
"""

import hashlib
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agent'))

from tools import swapper
from core.updater import AgentUpdater


class _FakeConfig:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.agent_id = 'test-agent'
        self.server_url = 'http://localhost:5050'
        self.api_token = 'token'
        self.api_key = 'key'
        self.current_version = '4.2.1'
        self.last_update_time = ''
        self.config = {'updates': {}}

    def save_config(self):
        pass


class TestPromoteSwapper(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.install = self.tmp / 'install'
        self.staging = self.tmp / 'staging'
        (self.install / 'tools').mkdir(parents=True)
        self.staging.mkdir()
        (self.install / 'tools' / 'swapper.exe').write_text('OLD-SWAPPER')

    def tearDown(self):
        self._tmp.cleanup()

    def test_promotes_new_swapper_from_staging(self):
        (self.staging / 'tools').mkdir()
        (self.staging / 'tools' / 'swapper.exe').write_text('NEW-SWAPPER')

        ok = swapper._promote_swapper(self.staging, self.install)

        self.assertTrue(ok)
        self.assertEqual(
            (self.install / 'tools' / 'swapper.exe').read_text(), 'NEW-SWAPPER'
        )

    def test_no_swapper_in_package_is_a_no_op(self):
        ok = swapper._promote_swapper(self.staging, self.install)

        self.assertFalse(ok)
        self.assertEqual(
            (self.install / 'tools' / 'swapper.exe').read_text(), 'OLD-SWAPPER'
        )

    def test_promotion_failure_never_raises(self):
        # The core update already succeeded by this point; failing to promote
        # the swapper must not turn a good swap into a failed one.
        (self.staging / 'tools').mkdir()
        (self.staging / 'tools' / 'swapper.exe').write_text('NEW-SWAPPER')

        with patch.object(swapper.shutil, 'copy2', side_effect=PermissionError('locked')):
            ok = swapper._promote_swapper(self.staging, self.install)

        self.assertFalse(ok)


class TestBackupIncludesSwapper(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.install = self.tmp / 'install'
        self.backup = self.tmp / 'backup'
        (self.install / 'tools').mkdir(parents=True)
        (self.install / 'windiag.exe').write_text('CORE')
        (self.install / 'syshealth.exe').write_text('HELPER')
        (self.install / 'version.json').write_text('{"version":"4.2.1"}')
        (self.install / 'tools' / 'swapper.exe').write_text('SWAPPER')

    def tearDown(self):
        self._tmp.cleanup()

    def test_backup_captures_the_swapper(self):
        swapper._backup_files(self.install, self.backup)

        self.assertTrue((self.backup / 'tools' / 'swapper.exe').is_file())
        self.assertEqual(
            (self.backup / 'tools' / 'swapper.exe').read_text(), 'SWAPPER'
        )

    def test_restore_puts_the_swapper_back(self):
        swapper._backup_files(self.install, self.backup)
        (self.install / 'tools' / 'swapper.exe').write_text('BROKEN-NEW')

        swapper._restore_backup(self.install, self.backup)

        self.assertEqual(
            (self.install / 'tools' / 'swapper.exe').read_text(), 'SWAPPER'
        )


class TestUpdaterStagesSwapper(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmp.name)
        self.install = self.data_dir / 'install'
        self.install.mkdir(parents=True)
        config = _FakeConfig(self.data_dir)
        with patch.object(AgentUpdater, '_detect_install_dir',
                          return_value=self.install):
            self.updater = AgentUpdater(config)

    def tearDown(self):
        self._tmp.cleanup()

    def _make_zip(self, with_swapper=True):
        zip_path = self.data_dir / 'pkg.zip'
        with zipfile.ZipFile(zip_path, 'w') as zf:
            zf.writestr('windiag.exe', 'CORE')
            zf.writestr('syshealth.exe', 'HELPER')
            if with_swapper:
                zf.writestr('tools/swapper.exe', 'NEW-SWAPPER-BYTES')
        return zip_path

    def test_stages_swapper_out_of_the_verified_package(self):
        staged = self.updater._stage_swapper(self._make_zip(), '4.3.0')

        self.assertIsNotNone(staged)
        self.assertTrue(staged.is_file())
        self.assertEqual(staged.read_bytes(), b'NEW-SWAPPER-BYTES')

    def test_returns_none_when_package_has_no_swapper(self):
        staged = self.updater._stage_swapper(
            self._make_zip(with_swapper=False), '4.3.0'
        )

        self.assertIsNone(staged)

    def test_trigger_exe_swap_prefers_the_staged_swapper(self):
        # The installed swapper is the OLD code; the staged one is the code
        # that shipped with this package and must be what actually runs.
        (self.install / 'tools').mkdir()
        (self.install / 'tools' / 'swapper.exe').write_text('OLD-SWAPPER')
        zip_path = self._make_zip()

        with patch.object(swapper.subprocess, 'Popen'):
            with patch('core.updater.subprocess.Popen') as popen:
                launched = self.updater.trigger_exe_swap(
                    zip_path, {'version': '4.3.0', 'package_sha256': 'abc'}
                )

        self.assertTrue(launched)
        argv = [str(a) for a in popen.call_args[0][0]]
        self.assertIn('swapper_run.exe', argv[0],
                      f"expected the staged swapper to be launched, got {argv}")

    def test_falls_back_to_installed_swapper_when_staging_fails(self):
        (self.install / 'tools').mkdir()
        (self.install / 'tools' / 'swapper.exe').write_text('OLD-SWAPPER')
        zip_path = self._make_zip(with_swapper=False)

        with patch('core.updater.subprocess.Popen') as popen:
            launched = self.updater.trigger_exe_swap(
                zip_path, {'version': '4.3.0', 'package_sha256': 'abc'}
            )

        self.assertTrue(launched)
        argv = [str(a) for a in popen.call_args[0][0]]
        self.assertIn('tools', argv[0])
        self.assertNotIn('swapper_run.exe', argv[0])


if __name__ == '__main__':
    unittest.main()
