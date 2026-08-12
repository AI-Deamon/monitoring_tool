"""
AgentUpdater lifecycle tests.

Covers the failure paths that can strand an agent in the field:
- concurrent update cycles (update.lock lifecycle, incl. the EXE-swap path)
- corrupted update_pending.json blocking every subsequent startup
- SHA256 mismatch handling (retry, then abort - never install a bad package)
- HMAC signature verification (must reject unsigned/tampered metadata)
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agent'))

from core.updater import AgentUpdater


class _FakeConfig:
    def __init__(self, data_dir, updates_cfg=None):
        self.data_dir = Path(data_dir)
        self.agent_id = 'test-agent'
        self.server_url = 'http://localhost:5050'
        self.api_token = 'token'
        self.api_key = 'key'
        self.current_version = '4.0.0'
        self.last_update_time = ''
        self.config = {'updates': updates_cfg or {}}

    def save_config(self):
        pass


class UpdaterTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmp.name)
        self.config = _FakeConfig(self.data_dir)
        with patch.object(AgentUpdater, '_detect_install_dir',
                          return_value=self.data_dir / 'install'):
            (self.data_dir / 'install').mkdir(parents=True, exist_ok=True)
            self.updater = AgentUpdater(self.config)

    def tearDown(self):
        self._tmp.cleanup()


class TestUpdateLock(UpdaterTestBase):
    def test_fresh_lock_blocks_concurrent_cycle(self):
        # A lock held by a process that is still alive must block.
        self.updater.update_lock_file.write_text('1234')
        self.updater.check_for_update = MagicMock()

        with patch.object(AgentUpdater, '_pid_is_running', return_value=True):
            result = self.updater.run_update_cycle()

        self.assertFalse(result)
        self.updater.check_for_update.assert_not_called()
        self.assertTrue(self.updater.update_lock_file.exists())

    def test_lock_released_when_no_update_available(self):
        self.updater.check_for_update = MagicMock(return_value=None)

        self.updater.run_update_cycle()

        self.assertFalse(
            self.updater.update_lock_file.exists(),
            "a transient no-op cycle must not leave the lock behind"
        )

    def test_lock_released_on_download_failure(self):
        self.updater.check_for_update = MagicMock(
            return_value={'version': '4.1.0'})
        self.updater.check_compatibility = MagicMock(return_value=(True, 'ok'))
        self.updater.report_status = MagicMock()
        self.updater.report_health = MagicMock()
        self.updater.download_update = MagicMock(return_value=None)

        result = self.updater.run_update_cycle()

        self.assertFalse(result)
        self.assertFalse(self.updater.update_lock_file.exists())

    def test_lock_held_across_exe_swap(self):
        """The swapper waits for THIS process to exit before replacing files -
        releasing the lock here would let a second cycle start mid-swap."""
        self.updater.check_for_update = MagicMock(return_value={
            'version': '4.1.0', 'artifact_type': 'exe_bundle'})
        self.updater.check_compatibility = MagicMock(return_value=(True, 'ok'))
        self.updater.report_status = MagicMock()
        self.updater.download_update = MagicMock(
            return_value=self.data_dir / 'pkg.zip')
        self.updater.trigger_exe_swap = MagicMock(return_value=True)

        result = self.updater.run_update_cycle()

        self.assertTrue(result)
        self.assertTrue(
            self.updater.update_lock_file.exists(),
            "lock must survive until the process exits for the swap"
        )

    def test_stale_lock_is_reclaimed(self):
        self.updater.update_lock_file.write_text('1234')
        stale = os.stat(self.updater.update_lock_file).st_mtime - 3600
        os.utime(self.updater.update_lock_file, (stale, stale))
        self.updater.check_for_update = MagicMock(return_value=None)

        self.updater.run_update_cycle()

        self.updater.check_for_update.assert_called_once()

    def test_lock_from_dead_process_is_reclaimed_immediately(self):
        """After an update the lock outlives the process that held it (the
        swapper replaces the EXE, then the service restarts). A pure age
        check would block every update for 30 minutes post-update."""
        self.updater.update_lock_file.write_text('4242')  # pre-restart PID
        self.updater.check_for_update = MagicMock(return_value=None)

        with patch.object(AgentUpdater, '_pid_is_running', return_value=False):
            self.updater.run_update_cycle()

        self.updater.check_for_update.assert_called_once()

    def test_lock_from_live_process_still_blocks(self):
        self.updater.update_lock_file.write_text('4242')
        self.updater.check_for_update = MagicMock()

        with patch.object(AgentUpdater, '_pid_is_running', return_value=True):
            result = self.updater.run_update_cycle()

        self.assertFalse(result)
        self.updater.check_for_update.assert_not_called()

    def test_unreadable_lock_is_reclaimed(self):
        self.updater.update_lock_file.write_text('not-a-pid')
        self.updater.check_for_update = MagicMock(return_value=None)

        self.updater.run_update_cycle()

        self.updater.check_for_update.assert_called_once()


class TestPendingUpdate(UpdaterTestBase):
    def test_valid_pending_is_returned(self):
        self.updater.pending_file.write_text(json.dumps({'version': '4.1.0'}))

        pending = self.updater.check_pending_update()

        self.assertEqual(pending['version'], '4.1.0')

    def test_corrupt_pending_is_discarded_not_left_to_refail(self):
        self.updater.pending_file.write_text('{ truncated json')

        pending = self.updater.check_pending_update()

        self.assertIsNone(pending)
        self.assertFalse(
            self.updater.pending_file.exists(),
            "an unreadable pending file must be removed, or every restart "
            "re-fails on it forever"
        )


class TestDownloadVerification(UpdaterTestBase):
    def _metadata(self):
        return {
            'version': '4.1.0',
            'package_sha256': 'a' * 64,
            'package_url': '/api/v1/updates/download/4.1.0',
        }

    def test_sha_mismatch_retries_then_aborts_without_installing(self):
        payload = b'corrupted-bytes'

        class _Resp:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *exc):
                return False

            def read(self_inner, n=-1):
                if getattr(self_inner, '_done', False):
                    return b''
                self_inner._done = True
                return payload

        with patch('core.updater.urllib.request.urlopen', return_value=_Resp()), \
                patch('core.updater.time.sleep'):
            result = self.updater.download_update(self._metadata())

        self.assertIsNone(result, "a package failing SHA256 must never be applied")


class TestRejectionIsReported(UpdaterTestBase):
    """
    check_for_update() returning None used to be treated as uniformly
    silent. An explicit local rejection (e.g. signature verification
    failure) after a valid server response was received must be reported
    to the server - otherwise agents.update_status is stuck at 'pending'
    forever, since /health is the only thing that ever moves it out.
    """

    def test_signature_rejection_reports_health_failed(self):
        self.updater._last_update_check_reason = 'signature_verification_failed'
        self.updater._last_rejected_version = '4.1.0'
        self.updater.check_for_update = MagicMock(return_value=None)
        self.updater.report_health = MagicMock()

        result = self.updater.run_update_cycle()

        self.assertFalse(result)
        self.updater.report_health.assert_called_once()
        args = self.updater.report_health.call_args[0]
        self.assertEqual(args[0], 'failed')
        self.assertEqual(args[1], '4.1.0')
        self.assertIn('signature_verification_failed', args[3])

    def test_update_check_error_reports_health_failed(self):
        self.updater._last_update_check_reason = 'update_check_error: boom'
        self.updater._last_rejected_version = None
        self.updater.check_for_update = MagicMock(return_value=None)
        self.updater.report_health = MagicMock()

        self.updater.run_update_cycle()

        self.updater.report_health.assert_called_once()
        args = self.updater.report_health.call_args[0]
        self.assertEqual(args[1], 'unknown', "no version was ever parsed - must not fabricate one")

    def test_no_update_available_does_not_report(self):
        self.updater._last_update_check_reason = 'no_update_available'
        self.updater.check_for_update = MagicMock(return_value=None)
        self.updater.report_health = MagicMock()

        self.updater.run_update_cycle()

        self.updater.report_health.assert_not_called()

    def test_already_up_to_date_does_not_report(self):
        self.updater._last_update_check_reason = 'already_up_to_date'
        self.updater.check_for_update = MagicMock(return_value=None)
        self.updater.report_health = MagicMock()

        self.updater.run_update_cycle()

        self.updater.report_health.assert_not_called()

    def test_server_unreachable_does_not_report(self):
        self.updater._last_update_check_reason = 'server_unreachable: [Errno 111] refused'
        self.updater.check_for_update = MagicMock(return_value=None)
        self.updater.report_health = MagicMock()

        self.updater.run_update_cycle()

        self.updater.report_health.assert_not_called(
        )

    def test_not_checked_does_not_report(self):
        """Never even attempted a check this cycle (e.g. blocked earlier) -
        nothing to report."""
        self.updater._last_update_check_reason = 'not_checked'
        self.updater.check_for_update = MagicMock(return_value=None)
        self.updater.report_health = MagicMock()

        self.updater.run_update_cycle()

        self.updater.report_health.assert_not_called()


class TestReportHealthRetry(UpdaterTestBase):
    """
    report_health() is the ONLY call that moves the server's update_status
    out of pending/downloading/installing. A single lost request under
    thread-pool contention must not permanently strand the dashboard.
    """

    def test_retries_on_transport_failure_then_succeeds(self):
        import urllib.error

        class _Resp:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *exc):
                return False

            def read(self_inner):
                return b'{"acknowledged": true}'

        calls = {'n': 0}

        def fake_urlopen(*args, **kwargs):
            calls['n'] += 1
            if calls['n'] < 3:
                raise urllib.error.URLError('timed out')
            return _Resp()

        with patch('core.updater.urllib.request.urlopen', side_effect=fake_urlopen), \
                patch('core.updater.time.sleep') as mock_sleep:
            self.updater.report_health('healthy', '4.1.0', '4.0.0')

        self.assertEqual(calls['n'], 3)
        self.assertEqual(mock_sleep.call_count, 2)

    def test_gives_up_after_max_retries_without_raising(self):
        import urllib.error

        with patch('core.updater.urllib.request.urlopen',
                   side_effect=urllib.error.URLError('timed out')), \
                patch('core.updater.time.sleep'):
            # Must not raise - a lost report is logged and swallowed, same
            # as before, just after exhausting retries instead of on the
            # first failure.
            self.updater.report_health('healthy', '4.1.0', '4.0.0')

    def test_not_acknowledged_is_not_retried(self):
        """A definitive response means the server already answered -
        retrying it only risks duplicate work, not recovering anything."""
        class _Resp:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *exc):
                return False

            def read(self_inner):
                return b'{"acknowledged": false}'

        with patch('core.updater.urllib.request.urlopen', return_value=_Resp()) as mock_open, \
                patch('core.updater.time.sleep') as mock_sleep:
            self.updater.report_health('healthy', '4.1.0', '4.0.0')

        self.assertEqual(mock_open.call_count, 1)
        mock_sleep.assert_not_called()


class TestSignatureVerification(UpdaterTestBase):
    def test_unsigned_metadata_rejected_when_key_configured(self):
        self.config.config['updates'] = {'signing_key': 'secret'}

        self.assertFalse(self.updater.verify_signature({'version': '4.1.0'}))

    def test_tampered_signature_rejected(self):
        self.config.config['updates'] = {'signing_key': 'secret'}
        metadata = {
            'version': '4.1.0',
            'package_sha256': 'b' * 64,
            'package_size': 1,
            'signature': 'bm90LWEtdmFsaWQtc2lnbmF0dXJl',
        }

        self.assertFalse(self.updater.verify_signature(metadata))

    def test_missing_key_rejects_unless_explicitly_allowed(self):
        self.config.config['updates'] = {}
        self.assertFalse(self.updater.verify_signature({'signature': 'x'}))

        self.config.config['updates'] = {'allow_unsigned_updates': True}
        self.assertTrue(self.updater.verify_signature({'signature': 'x'}))

    def test_valid_signature_accepted(self):
        import base64
        import hashlib
        import hmac

        key = 'secret'
        self.config.config['updates'] = {'signing_key': key}
        signable = {
            'version': '4.1.0',
            'package_sha256': 'c' * 64,
            'package_size': 100,
            'min_agent_version': '2.0.0',
            'mandatory': False,
        }
        canonical = json.dumps(signable, sort_keys=True, separators=(',', ':'))
        sig = base64.b64encode(hmac.new(
            key.encode(), canonical.encode(), hashlib.sha256
        ).digest()).decode()

        self.assertTrue(
            self.updater.verify_signature({**signable, 'signature': sig}))


if __name__ == '__main__':
    unittest.main()
