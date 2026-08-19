"""
The uploader must acknowledge every success status the server actually returns.

## The defect

`Uploader._is_ack_success()` accepted only ('ok', 'success', 'skipped'). The
asset endpoints answer with the ACTION they performed instead:

    /asset-hardware          -> {'status': 'created'} | {'status': 'updated'}
    /asset-hardware/network  -> {'status': 'network_updated'}

So a successful upload was read as a failure. `_upload_hardware()` breaks on
the first unacknowledged record, which turned the OLDEST buffered snapshot into
a permanent head-of-line block: re-sent and re-applied on every cycle, with
every newer snapshot queued behind it forever.

## Observed impact (L180701PB, 2026-08-12)

    hardware_snapshots: 251 rows, ALL uploaded=0
    oldest row id=9,   2026-05-21, primary_ip=10.37.230.153 (Wi-Fi, since
                       disconnected)
    newest row id=281, 2026-08-12, primary_ip=192.168.1.79  (current Ethernet)

The dashboard showed the May address for three months. Because the server sets
`collected_at = datetime.now()` on arrival, the stale row looked freshly
collected every time it was re-applied, which is what made this so hard to see.

It also meant the battery-health fix could never have reached the dashboard:
the new snapshot would have queued behind the same block.

HTTP 304 is separately normalised to 'ok' inside `_make_request`, so
'unchanged' was never the blocker.
"""
import ast
import re
from pathlib import Path

import pytest

from core.uploader import ServerUploader as Uploader

SERVER_API = Path(__file__).resolve().parent.parent / "server" / "server_api.py"


class TestAckStatuses:
    """Statuses the asset upload paths depend on."""

    @pytest.mark.parametrize(
        "status",
        ["ok", "success", "skipped", "created", "updated", "network_updated"],
    )
    def test_success_status_is_acknowledged(self, status):
        assert Uploader._is_ack_success(Uploader, {"status": status}) is True, (
            f"{status!r} is a successful server response; not acknowledging it "
            f"leaves the buffered record unmarked and blocks the whole queue"
        )

    @pytest.mark.parametrize("status", ["error", "rejected", "failed"])
    def test_failure_status_is_not_acknowledged(self, status):
        assert Uploader._is_ack_success(Uploader, {"status": status}) is False

    def test_empty_response_is_not_acknowledged(self):
        assert Uploader._is_ack_success(Uploader, None) is False
        assert Uploader._is_ack_success(Uploader, {}) is False

    def test_status_match_is_case_insensitive(self):
        assert Uploader._is_ack_success(Uploader, {"status": "Network_Updated"}) is True


class TestServerContract:
    """
    Cross-file contract: every literal success status server_api.py returns
    must be accepted by the uploader. This is what stops the two sides drifting
    apart again -- the original bug was exactly such a drift.
    """

    @staticmethod
    def _server_success_statuses():
        """Literal statuses returned with a 2xx/304 code by server_api.py."""
        source = SERVER_API.read_text(encoding="utf-8")
        tree = ast.parse(source)
        found = set()

        for node in ast.walk(tree):
            if not isinstance(node, ast.Return) or not isinstance(node.value, ast.Tuple):
                continue
            elts = node.value.elts
            if len(elts) != 2:
                continue
            code = elts[1]
            if not (isinstance(code, ast.Constant) and isinstance(code.value, int)):
                continue
            if not (200 <= code.value < 400):
                continue
            call = elts[0]
            if not (isinstance(call, ast.Call)
                    and getattr(call.func, "id", "") == "jsonify"
                    and call.args
                    and isinstance(call.args[0], ast.Dict)):
                continue
            for key, value in zip(call.args[0].keys, call.args[0].values):
                if (isinstance(key, ast.Constant) and key.value == "status"
                        and isinstance(value, ast.Constant)
                        and isinstance(value.value, str)):
                    found.add(value.value.lower())
        return found

    def test_server_file_is_present(self):
        assert SERVER_API.is_file(), f"missing {SERVER_API}"

    def test_every_server_success_status_is_acknowledged(self):
        statuses = self._server_success_statuses()
        assert statuses, "parsed no statuses from server_api.py - check the parser"

        # 'error' is returned with 4xx/5xx elsewhere; if it appears on a 2xx it
        # is still a failure from the agent's point of view.
        expected = {s for s in statuses if s != "error"}

        missing = {
            s for s in expected
            if not Uploader._is_ack_success(Uploader, {"status": s})
        }
        assert not missing, (
            f"server_api.py returns {sorted(missing)} with a success HTTP code, "
            f"but the uploader treats them as failures. Buffered records will "
            f"never be marked uploaded and the queue will block."
        )

    def test_the_three_asset_statuses_are_present_in_the_server(self):
        """Guards the parser itself: these must be found, or the test is vacuous."""
        statuses = self._server_success_statuses()
        for required in ("network_updated", "unchanged"):
            assert required in statuses, (
                f"{required!r} not found in server_api.py - the AST parser has "
                f"probably stopped matching and this suite is no longer checking "
                f"anything"
            )

    def test_action_statuses_are_covered(self):
        """
        /asset-hardware returns `jsonify({'status': action})` where action is a
        VARIABLE ('created'/'updated'), so the AST scan cannot see it. Pin the
        two values explicitly.
        """
        source = SERVER_API.read_text(encoding="utf-8")
        assert re.search(r"action\s*=\s*['\"]created['\"]", source)
        assert re.search(r"action\s*=\s*['\"]updated['\"]", source)
        for status in ("created", "updated"):
            assert Uploader._is_ack_success(Uploader, {"status": status}) is True
