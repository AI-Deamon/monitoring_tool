"""
Network collection defects D22 and D23 (feature 037).

D22 / FR-031 — the reported primary IP must be the address of the physical
adapter carrying the current connection (Ethernet's address on cable, Wi-Fi's
when wireless), not the address that happens to route to the internet.

Root cause: a block labelled "Python fallback" ran unconditionally and
overwrote the CIM-derived address with `socket.connect(("8.8.8.8", 80))`'s
local address. That answers "which interface reaches the internet?", which is
a different question — on VPN it is the tunnel address, on a multi-adapter host
it is whichever holds the default route, and with no route at all it fell
through to 127.0.0.1.

D23 / FR-034 — a change of primary IP must be reported even when the set of
addresses is unchanged.

Root cause: the change-detection hash covered all_macs, all_ips, dns_servers,
domain_joined and domain_name but NOT primary_ip. With Ethernet and Wi-Fi both
active, both addresses already appear in all_ips, so moving the connection
between them left the hash identical and the update was filtered out before
upload. The server kept the stale address indefinitely.
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'monitoring_tool', 'agent'))

from helper.hardware_collector import HardwareCollector


ETH = {
    'MAC': 'B4-B6-86-BD-0B-A9',
    'IPs': ['192.168.1.79'],
    'Description': 'Realtek PCIe GbE Family Controller',
    'DefaultGateway': ['192.168.1.1'],
}
WIFI = {
    'MAC': 'AA-BB-CC-DD-EE-FF',
    'IPs': ['192.168.1.120'],
    'Description': 'Intel Wi-Fi 6 AX201 160MHz',
    'DefaultGateway': ['192.168.1.1'],
}
VPN = {
    'MAC': '00-00-00-00-00-01',
    'IPs': ['10.8.0.6'],
    'Description': 'TAP-Windows Adapter V9 VPN Tunnel',
    'DefaultGateway': ['10.8.0.1'],
}
HYPERV = {
    'MAC': '00-15-5D-00-00-01',
    'IPs': ['172.20.16.1'],
    'Description': 'Hyper-V Virtual Ethernet Adapter',
    'DefaultGateway': [],
}


class TestPrimaryIpSelection(unittest.TestCase):
    """D22 / FR-031."""

    def test_picks_the_only_physical_adapter(self):
        self.assertEqual(
            HardwareCollector._select_primary_ip([ETH], ['192.168.1.79']),
            '192.168.1.79',
        )

    def test_prefers_physical_adapter_over_vpn_tunnel(self):
        """On VPN the tunnel holds the internet route; the LAN address is wanted."""
        self.assertEqual(
            HardwareCollector._select_primary_ip([VPN, ETH], ['10.8.0.6', '192.168.1.79']),
            '192.168.1.79',
        )

    def test_prefers_physical_adapter_over_virtual_switch(self):
        self.assertEqual(
            HardwareCollector._select_primary_ip([HYPERV, ETH], ['172.20.16.1', '192.168.1.79']),
            '192.168.1.79',
        )

    def test_prefers_gatewayed_adapter_when_two_physical_are_up(self):
        no_gw_eth = dict(ETH, DefaultGateway=[])
        self.assertEqual(
            HardwareCollector._select_primary_ip([no_gw_eth, WIFI], ['192.168.1.79', '192.168.1.120']),
            '192.168.1.120',
        )

    def test_never_returns_loopback_when_a_real_address_is_known(self):
        """The offline / no-default-route case that previously yielded 127.0.0.1."""
        result = HardwareCollector._select_primary_ip([dict(ETH, DefaultGateway=[])], ['192.168.1.79'])
        self.assertNotEqual(result, '127.0.0.1')
        self.assertEqual(result, '192.168.1.79')

    def test_falls_back_to_all_ips_when_adapter_map_is_empty(self):
        self.assertEqual(
            HardwareCollector._select_primary_ip([], ['192.168.1.79']),
            '192.168.1.79',
        )

    def test_returns_empty_when_nothing_is_known(self):
        self.assertEqual(HardwareCollector._select_primary_ip([], []), '')

    def test_ignores_ipv6_addresses(self):
        adapter = dict(ETH, IPs=['fe80::25a4:a79e:542c:2cf7', '192.168.1.79'])
        self.assertEqual(
            HardwareCollector._select_primary_ip([adapter], ['192.168.1.79']),
            '192.168.1.79',
        )


class TestNetworkChangeDetectionIncludesPrimaryIp(unittest.TestCase):
    """
    D23 / FR-034 — the Ethernet-to-Wi-Fi switch must not be suppressed when both
    adapters are simultaneously active and the address set is unchanged.
    """

    def _collector(self):
        collector = HardwareCollector.__new__(HardwareCollector)
        collector.last_hash = None
        collector.last_network_hash = None
        collector.config = None          # collect_network_partial reads agent_id from it
        collector._save_state = lambda *a, **k: None
        return collector

    def _network(self, primary_ip):
        from helper.hardware_collector import NetworkInfo
        n = NetworkInfo()
        # Both adapters are up, so the address SET never changes — only which one
        # is primary does. This is the case that was being filtered out.
        n.all_ips = ['192.168.1.79', '192.168.1.120']
        n.all_macs = [ETH['MAC'], WIFI['MAC']]
        n.dns_servers = ['192.168.1.227']
        n.domain_joined = True
        n.domain_name = 'corp.local'
        n.primary_ip = primary_ip
        n.primary_mac = ETH['MAC'] if primary_ip == '192.168.1.79' else WIFI['MAC']
        return n

    def test_primary_ip_change_is_reported(self):
        collector = self._collector()
        collector._collect_network = lambda: self._network('192.168.1.79')
        first = collector.collect_network_partial()
        self.assertIsNotNone(first, 'first collection must always report')

        # Cable unplugged: connection moves to Wi-Fi. Same address set.
        collector._collect_network = lambda: self._network('192.168.1.120')
        second = collector.collect_network_partial()
        self.assertIsNotNone(
            second,
            'a primary_ip change must be reported even though all_ips is unchanged'
        )
        self.assertEqual(second['network']['primary_ip'], '192.168.1.120')
        self.assertEqual(second['update_type'], 'network_partial')

    def test_identical_state_is_still_suppressed(self):
        """The de-duplication must keep working for genuinely unchanged state."""
        collector = self._collector()
        collector._collect_network = lambda: self._network('192.168.1.79')
        self.assertIsNotNone(collector.collect_network_partial())
        self.assertIsNone(
            collector.collect_network_partial(),
            'unchanged network state must not be re-uploaded'
        )


if __name__ == '__main__':
    unittest.main()
