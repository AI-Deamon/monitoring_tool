"""
A network partial must be applied whole or not at all.

## The defect

`/asset-hardware/network` mixed two update styles in one handler:

    existing.primary_mac   = network.get('primary_mac', '') or existing.primary_mac
    existing.primary_ip    = network.get('primary_ip', '')  or existing.primary_ip
    existing.all_macs_json = json.dumps(network.get('all_macs', []))
    existing.all_ips_json  = json.dumps(network.get('all_ips', []))

Scalars fell back to the stored value when the payload was blank; lists were
overwritten unconditionally. An empty payload therefore produced a row that
was internally contradictory — a primary_ip retained from an older reading
next to an empty all_ips — and refreshed collected_at, so a stale address
looked freshly verified. The fallback also made primary_ip monotonically
sticky: once a wrong address was stored, no empty payload could ever clear it.

## Observed impact (L211001EA, 2026-08-13)

    machine (ipconfig):  192.168.1.55  on an ASIX AX88772C USB Ethernet adapter
    dashboard:           10.73.111.223, all_ips=[], collected_at = minutes ago

A USB NIC renegotiating its link leaves nothing IPEnabled for a moment, so the
agent collected an all-blank reading and uploaded it as a change. Those empty
partials had been buffering unsent behind the ACK defect (see
test_upload_ack_statuses.py); 4.2.5 unblocked the queue and they began draining,
each one re-applying the half-update.

## The fix

Agents guard this from 4.2.5 on, but the handler must hold the line for every
already-deployed agent and for empty partials still sitting in buffers.

The empty case answers 200/'skipped' rather than 4xx deliberately: 'skipped' is
in ServerUploader.ACK_SUCCESS_STATUSES, so the agent marks the record uploaded
and moves on. A 4xx would fail the ACK, and `_upload_network_partials()` breaks
on first failure — so the bad record would block every newer one behind it,
recreating exactly the head-of-line stall 4.2.5 just fixed.
"""
import ast
import sys
from pathlib import Path

import pytest

sys.path.insert(0, __file__.rsplit('tests', 1)[0] + 'server')

from server_api import normalize_network_addresses  # noqa: E402

HANDLER = 'asset_hardware_network'
SOURCE = Path(__file__).resolve().parents[1] / 'server' / 'server_api.py'


class TestNormalizeNetworkAddresses:
    """
    The guard's predicate. Blank-but-present values are the normal shape of an
    empty reading, so testing for key presence alone would let them through.
    """

    @pytest.mark.parametrize('payload', [
        {},
        {'primary_ip': '', 'all_ips': []},
        {'primary_ip': '   ', 'all_ips': ['']},
        {'primary_ip': None, 'all_ips': [None, '']},
        {'all_ips': []},
        {'primary_ip': ''},
        None,
        'not-a-dict',
    ])
    def test_empty_shapes_normalise_to_nothing(self, payload):
        primary_ip, all_ips = normalize_network_addresses(payload)
        assert not primary_ip and not all_ips

    def test_primary_ip_alone_counts_as_present(self):
        primary_ip, all_ips = normalize_network_addresses(
            {'primary_ip': '192.168.1.55', 'all_ips': []}
        )
        assert primary_ip == '192.168.1.55'
        assert all_ips == []

    def test_all_ips_alone_counts_as_present(self):
        primary_ip, all_ips = normalize_network_addresses(
            {'primary_ip': '', 'all_ips': ['192.168.1.55']}
        )
        assert primary_ip == ''
        assert all_ips == ['192.168.1.55']

    def test_whitespace_is_stripped(self):
        primary_ip, all_ips = normalize_network_addresses(
            {'primary_ip': ' 192.168.1.55 ', 'all_ips': [' 192.168.1.55 ']}
        )
        assert primary_ip == '192.168.1.55'
        assert all_ips == ['192.168.1.55']

    def test_blank_entries_are_dropped_but_real_ones_kept(self):
        _, all_ips = normalize_network_addresses(
            {'all_ips': ['', None, '192.168.1.55', '   ', '192.168.56.1']}
        )
        assert all_ips == ['192.168.1.55', '192.168.56.1']


def _handler_ast():
    tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == HANDLER:
            return node
    pytest.fail(f'{HANDLER}() not found in {SOURCE.name}')


class TestHandlerContract:
    """
    Source-level guards. The behaviour lives inside a Flask route that needs a
    request context and a live session to call, and importing this codebase's
    server modules reaches the real dev Postgres (server_config.py calls
    load_dotenv(override=True)), so the contract is asserted against the AST.
    """

    def test_sticky_primary_ip_fallback_is_not_reintroduced(self):
        """
        `network.get('primary_ip', '') or existing.primary_ip` is the defect
        itself: it preserves a stale address across an empty payload while the
        list fields beside it are wiped.
        """
        offenders = []
        for node in ast.walk(_handler_ast()):
            if not isinstance(node, ast.Assign):
                continue
            if not isinstance(node.value, ast.BoolOp):
                continue
            if not isinstance(node.value.op, ast.Or):
                continue
            for target in node.targets:
                if (isinstance(target, ast.Attribute)
                        and target.attr in ('primary_ip', 'primary_mac',
                                            'all_ips_json', 'all_macs_json')):
                    offenders.append(f'{target.attr} (line {node.lineno})')

        assert not offenders, (
            'network address fields must not fall back to the stored value on '
            'an empty payload — that is what left primary_ip set beside an '
            f'empty all_ips: {offenders}'
        )

    def test_empty_payload_is_acknowledged_not_rejected(self):
        """
        The empty branch must answer 200/'skipped'. A 4xx would fail the agent's
        ACK check and head-of-line block the partial queue.
        """
        statuses = {}
        for node in ast.walk(_handler_ast()):
            if not isinstance(node, ast.Return):
                continue
            if not isinstance(node.value, ast.Tuple) or len(node.value.elts) != 2:
                continue
            call, code = node.value.elts
            if not (isinstance(code, ast.Constant) and isinstance(code.value, int)):
                continue
            if not (isinstance(call, ast.Call)
                    and getattr(call.func, 'id', '') == 'jsonify'
                    and call.args
                    and isinstance(call.args[0], ast.Dict)):
                continue
            for key, value in zip(call.args[0].keys, call.args[0].values):
                if (isinstance(key, ast.Constant) and key.value == 'status'
                        and isinstance(value, ast.Constant)):
                    statuses[value.value] = code.value

        assert 'skipped' in statuses, (
            "the empty-payload branch must answer {'status': 'skipped'}"
        )
        assert statuses['skipped'] == 200, (
            f"'skipped' must be HTTP 200, got {statuses['skipped']} — a non-2xx "
            'fails the agent ACK and blocks every queued record behind it'
        )

    def test_skipped_is_an_accepted_ack_status(self):
        """
        The chosen status only works if the uploader treats it as success.
        Guards against the two sides drifting apart.
        """
        sys.path.insert(0, __file__.rsplit('tests', 1)[0] + 'agent')
        from core.uploader import ServerUploader

        assert 'skipped' in ServerUploader.ACK_SUCCESS_STATUSES

    def test_guard_runs_before_any_field_is_written(self):
        """
        Ordering is the whole point: the early return must precede the
        assignments, or the row is already corrupted by the time we bail.
        """
        handler = _handler_ast()

        guard_line = None
        for node in ast.walk(handler):
            if (isinstance(node, ast.Call)
                    and getattr(node.func, 'id', '') == 'normalize_network_addresses'):
                guard_line = node.lineno
                break
        assert guard_line, 'handler must normalise the payload before using it'

        writes = [
            node.lineno for node in ast.walk(handler)
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Attribute)
            and target.attr.startswith(('primary_', 'all_', 'dns_'))
        ]
        assert writes, 'expected the handler to write network fields'
        assert guard_line < min(writes), (
            'the empty-payload guard must run before any field is written'
        )
