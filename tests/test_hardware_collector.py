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


if __name__ == '__main__':
    unittest.main()
