import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('monitor', Path(__file__).resolve().parents[3] / 'scripts/lab_resource_monitor.py')
monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitor)


class MonitorTests(unittest.TestCase):
    def sample(self):
        return dict(boot_id='boot1', uptime_seconds=300,
            memory=dict(total_bytes=100, available_bytes=20, swap_total_bytes=100, swap_free_bytes=1),
            swap_pages=dict(pswpin=100, pswpout=200),
            disks={'lab': dict(total_bytes=100, used_bytes=20, free_bytes=80)},
            collectors={'market': dict(age_seconds=100, warn_after_seconds=1800)},
            containers=[dict(name='paper', state='running', health='healthy')])

    def test_full_swap_is_not_active_swapping(self):
        prior = self.sample()
        current = self.sample()
        current['uptime_seconds'] += 300
        result = monitor.assess(current, prior)
        self.assertEqual(result['swap_bytes_per_second'], dict(pswpin=0, pswpout=0))
        self.assertEqual(result['alerts'], ['SWAP_OCCUPANCY_HIGH_NOT_PROOF_OF_THRASHING'])

    def test_restart_does_not_compare_counter_epochs(self):
        prior = self.sample()
        current = self.sample()
        current['boot_id'] = 'boot2'
        self.assertNotIn('swap_bytes_per_second', monitor.assess(current, prior))

    def test_stale_health_and_unavailable_runtime_are_explicit(self):
        sample = self.sample()
        sample['collectors']['market']['age_seconds'] = 1801
        sample['container_error'] = 'UNAVAILABLE'
        alerts = monitor.assess(sample)['alerts']
        self.assertIn('COLLECTOR_STALE_OR_UNREADABLE:market', alerts)
        self.assertIn('CONTAINER_STATE_UNAVAILABLE', alerts)

    def test_pressure_thresholds_and_growth(self):
        prior = self.sample()
        sample = copy.deepcopy(prior)
        sample['memory']['available_bytes'] = 9
        sample['disks']['lab'].update(used_bytes=90, free_bytes=10)
        result = monitor.assess(sample, prior)
        self.assertIn('MEMORY_AVAILABLE_BELOW_10_PERCENT', result['alerts'])
        self.assertIn('DISK_FREE_BELOW_15_PERCENT:lab', result['alerts'])
        self.assertEqual(result['disks']['lab']['used_delta_bytes'], 70)

    def test_recovery_retains_observed_gap(self):
        prior = self.sample()
        prior['collectors']['market'].update(collection_state='UNAVAILABLE_OR_STALE',
            last_success_at='2026-10-09T00:00:00+00:00')
        current = self.sample()
        current['collectors']['market']['last_success_at'] = '2026-10-09T01:00:00+00:00'
        result = monitor.assess(current, prior)['collectors']['market']
        self.assertTrue(result['recovered_since_previous_sample'])
        self.assertEqual(result['success_interval_seconds'], 3600)
