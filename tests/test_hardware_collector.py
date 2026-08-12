import os
import sys
import unittest
import json


sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'monitoring_tool', 'agent'))

from helper.hardware_collector import HardwareCollector


class TestHardwareCollectorNormalization(unittest.TestCase):
    def test_normalize_powershell_scalar_uses_first_item_for_single_item_list(self):
        self.assertEqual(
            HardwareCollector._normalize_powershell_scalar(['10.0.0.25']),
            '10.0.0.25'
        )

    def test_normalize_powershell_list_wraps_single_string(self):
        self.assertEqual(
            HardwareCollector._normalize_powershell_list('10.0.0.25'),
            ['10.0.0.25']
        )

    def test_normalize_powershell_list_preserves_multiple_items(self):
        self.assertEqual(
            HardwareCollector._normalize_powershell_list(['10.0.0.25', '10.0.0.26']),
            ['10.0.0.25', '10.0.0.26']
        )

    def test_collect_hardware_keeps_gpu_when_memory_is_zero(self):
        collector = HardwareCollector.__new__(HardwareCollector)
        collector._run_powershell = lambda script, timeout=30: json.dumps({
            'CPU_Name': 'Intel Test CPU',
            'CPU_Cores': 4,
            'CPU_Threads': 8,
            'CPU_Speed': 2400,
            'RAM_Total': 16 * 1024**3,
            'RAM_SlotsUsed': 1,
            'RAM_SlotsTotal': 2,
            'GPUs': [{'Name': 'NVIDIA Test GPU', 'MemoryGB': 0}],
            'Disks': [],
            'Motherboard': 'Test Board',
        })

        hardware = collector._collect_hardware()

        self.assertEqual(len(hardware.gpus), 1)
        self.assertEqual(hardware.gpus[0].name, 'NVIDIA Test GPU')
        self.assertEqual(hardware.gpus[0].memory_gb, 0.0)


class TestCpuCoresNotBackfilledFromLogicalProcessors(unittest.TestCase):
    """
    D07 / FR-016, FR-016a — the field labelled physical cores must never be
    populated from the logical-processor count.

    Root cause: when the CIM query returns 0 for CPU_Cores, a fallback assigned
    os.cpu_count() — which reports LOGICAL processors on Windows. The dashboard
    then showed "16 Cores / 16 Threads" on a hyperthreaded machine. The happy
    path was always correct; only the degraded path lied.
    """

    def _collector_with_cores(self, cores):
        collector = HardwareCollector.__new__(HardwareCollector)
        collector._run_powershell = lambda script, timeout=30: json.dumps({
            'CPU_Name': 'Intel Test CPU',
            'CPU_Cores': cores,
            'CPU_Threads': 16,
            'CPU_Speed': 2400,
            'RAM_Total': 16 * 1024**3,
            'RAM_SlotsUsed': 1,
            'RAM_SlotsTotal': 2,
            'GPUs': [],
            'Disks': [],
            'Motherboard': 'Test Board',
        })
        return collector

    def test_physical_cores_preserved_when_query_succeeds(self):
        hardware = self._collector_with_cores(8)._collect_hardware()
        self.assertEqual(hardware.cpu_cores, 8)
        self.assertEqual(hardware.cpu_threads, 16)

    def test_cores_left_unknown_when_query_returns_zero(self):
        """Must stay 0 (explicitly unknown, FR-017), NOT os.cpu_count()."""
        hardware = self._collector_with_cores(0)._collect_hardware()
        self.assertEqual(
            hardware.cpu_cores, 0,
            'physical core count must be left unknown rather than backfilled '
            'from the logical-processor count'
        )

    def test_cores_never_equal_threads_via_fallback(self):
        """The reported symptom: cores and threads showing the same number."""
        hardware = self._collector_with_cores(0)._collect_hardware()
        self.assertNotEqual(
            hardware.cpu_cores, hardware.cpu_threads,
            'cores must not silently become the thread count'
        )


class TestBiosVersionIsCollected(unittest.TestCase):
    """
    D06 / FR-015 — the firmware version must be parsed, not discarded.

    Root cause: the PowerShell query already selected SMBIOSBIOSVersion, but the
    Python parser never read it, no column existed to store it, the API served
    bios_uuid (a GUID) instead, and the dashboard field was a static placeholder.
    Broken at every layer.
    """

    def _identity_from(self, payload):
        collector = HardwareCollector.__new__(HardwareCollector)
        collector._run_powershell = lambda script, timeout=30: json.dumps(payload)
        return collector._collect_identity()

    def test_bios_version_parsed_from_payload(self):
        identity = self._identity_from({
            'Manufacturer': 'LENOVO',
            'Model': '20XW',
            'SerialNumber': 'PF2ABCDE',
            'BIOSVersion': 'N2WET33W (1.23)',
            'UUID': '4C4C4544-0043-5A10-8046-CAC04F485833',
            'AssetTag': 'PF2ABCDE',
            'Domain': 'corp.local',
            'PartOfDomain': True,
        })
        self.assertEqual(identity.bios_version, 'N2WET33W (1.23)')

    def test_bios_version_is_not_the_bios_uuid(self):
        """The reported symptom: a GUID (or a dash) where a version belongs."""
        identity = self._identity_from({
            'BIOSVersion': 'N2WET33W (1.23)',
            'UUID': '4C4C4544-0043-5A10-8046-CAC04F485833',
        })
        self.assertNotEqual(identity.bios_version, identity.bios_uuid)

    def test_bios_version_handles_oem_array(self):
        """Some OEM hardware returns SMBIOSBIOSVersion as an array."""
        identity = self._identity_from({
            'BIOSVersion': ['1.15.0', 'extra'],
            'UUID': 'abc',
        })
        self.assertEqual(identity.bios_version, '1.15.0')

    def test_bios_version_empty_when_absent(self):
        identity = self._identity_from({'UUID': 'abc'})
        self.assertEqual(identity.bios_version, '')


class TestOsBuildIncludesRevision(unittest.TestCase):
    """
    D05 / FR-014 — the OS build must include the UBR revision component.

    Win32_OperatingSystem.BuildNumber yields only the base build (e.g. 26100).
    What winver and Settings show is <BuildNumber>.<UBR> (e.g. 26100.4061), and
    the revision is precisely the part that distinguishes patch levels — the
    reason a build number is useful for an audit at all.
    """

    def _security_from(self, payload):
        collector = HardwareCollector.__new__(HardwareCollector)
        collector._run_powershell = lambda script, timeout=30: json.dumps(payload)
        return collector._collect_security()

    def test_build_includes_revision_when_ubr_present(self):
        security = self._security_from({
            'OSCaption': 'Microsoft Windows 11 Pro',
            'OSVersion': '10.0.26100',
            'OSBuild': '26100',
            'OSUBR': 4061,
            'DisplayVersion': '25H2',
            'OSArchitecture': '64-bit',
            'Antivirus': [],
            'FirewallEnabled': True,
        })
        self.assertEqual(security.os_build, '26100.4061')

    def test_build_falls_back_to_base_when_ubr_missing(self):
        security = self._security_from({
            'OSBuild': '26100',
            'Antivirus': [],
        })
        self.assertEqual(security.os_build, '26100')

    def test_revision_not_duplicated_if_already_present(self):
        security = self._security_from({
            'OSBuild': '26100.4061',
            'OSUBR': 4061,
            'Antivirus': [],
        })
        self.assertEqual(security.os_build, '26100.4061')


if __name__ == '__main__':
    unittest.main()
