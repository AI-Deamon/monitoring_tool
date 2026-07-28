"""
Regression test for the screentime-rejection retry loop.

Symptom observed in production logs: the same handful of already-invalid
screentime snapshots (bucket sum > 86400s, e.g. a stale total captured
before/during a state-machine overflow) get resent to
POST /telemetry/screentime on every upload cycle and rejected with HTTP 400
every single time, forever - flooding server logs with identical
"screentime REJECTED" lines without any new data ever being accepted.

Root cause: ServerUploader._make_request() collapses every HTTP failure
(network error, 401, 403, 500, 400 validation rejection) down to the same
`None` return value, so ServerUploader._upload_merged_events() cannot tell
a permanent validation failure (payload will NEVER succeed, no matter how
many times it's resent) apart from a transient one (worth retrying next
cycle). Permanently-invalid rows in the `merged_events` buffer table are
therefore retried indefinitely instead of being dropped after one attempt.
"""
import json
import logging
import os
import shutil
import sys
import tempfile
import types
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))

from core.buffer import BufferDB
from core.uploader import ServerUploader


def _make_bare_uploader(buffer: BufferDB) -> ServerUploader:
    """Construct a ServerUploader without running __init__ (which needs a
    full CoreConfig, cert store, etc.) - only .buffer/.logger are needed to
    exercise _upload_merged_events()/_make_request()."""
    uploader = ServerUploader.__new__(ServerUploader)
    uploader.buffer = buffer
    uploader.logger = logging.getLogger("test.uploader")
    uploader.config = types.SimpleNamespace(
        server_url="https://server.example",
        allow_insecure_http=True,
        registration_secret=None,
    )
    uploader.registered = True
    uploader.auth_failed = False
    uploader.enabled = True
    uploader.last_warning_time = {}
    uploader.warning_interval = 60
    return uploader


class TestPermanentlyInvalidScreentimeIsNotRetriedForever(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.buffer = BufferDB(self.tmp_dir / "buffer.db")
        self.uploader = _make_bare_uploader(self.buffer)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _store_overflowing_screentime_event(self):
        # Mirrors a real rejected payload from production logs:
        # A=29992 I=4167 L=11074 W=83028 -> sum=128261s > 86400s
        self.buffer.store_merged_event({
            "agent_id": "2129fc-test",
            "username": "unittest",
            "type": "screentime",
            "timestamp": "2026-07-27T10:00:00+05:30",
            "session_start": "2026-07-27T00:00:00+05:30",
            "active_seconds": 29992,
            "idle_seconds": 4167,
            "locked_seconds": 11074,
            "away_seconds": 83028,
            "current_state": "active",
            "is_final_day": False,
            "final_day_date": None,
        })

    def test_400_response_is_reported_as_permanent_rejection(self):
        """_make_request must distinguish a validation 400 (never
        retryable) from transient failures (network/401/403/5xx)."""
        http_error = urllib.error.HTTPError(
            url="https://server/api/v1/telemetry/screentime",
            code=400,
            msg="Bad Request",
            hdrs=None,
            fp=None,
        )
        # HTTPError.read() is used by _make_request to log the body.
        http_error.read = lambda: b'{"error": "Invalid screentime total"}'

        with patch("urllib.request.urlopen", side_effect=http_error):
            response = self.uploader._make_request(
                "/telemetry/screentime", {"x": 1}, use_auth=False
            )

        self.assertTrue(
            self.uploader._is_permanent_rejection(response),
            f"expected a permanent-rejection marker for HTTP 400, got {response!r}",
        )

    def test_permanently_invalid_event_is_dropped_not_retried_forever(self):
        """After a single 400 rejection, the buffered event must be marked
        uploaded (dropped) so it stops being resent on every cycle."""
        self._store_overflowing_screentime_event()

        with patch.object(
            self.uploader,
            "_make_request",
            return_value={"status": "rejected", "http_code": 400},
        ) as mock_request:
            self.uploader._upload_merged_events()
            self.uploader._upload_merged_events()
            self.uploader._upload_merged_events()

        # The permanently-invalid payload should only ever be sent once -
        # not resent on every subsequent upload cycle.
        self.assertEqual(
            mock_request.call_count, 1,
            "permanently-rejected event was resent instead of being dropped after the first attempt",
        )

        pending = self.buffer.get_unuploaded_merged_events()
        self.assertEqual(
            len(pending), 0,
            "permanently-invalid screentime event should be dropped from the retry queue",
        )

    def test_transient_failure_is_still_retried(self):
        """A genuine transient failure (e.g. network error / 5xx, modeled
        here as None from _make_request) must still be retried next cycle -
        only permanent validation rejections should be dropped."""
        self._store_overflowing_screentime_event()

        with patch.object(self.uploader, "_make_request", return_value=None):
            self.uploader._upload_merged_events()

        pending = self.buffer.get_unuploaded_merged_events()
        self.assertEqual(
            len(pending), 1,
            "transient failures must remain queued for retry",
        )


if __name__ == "__main__":
    unittest.main()
